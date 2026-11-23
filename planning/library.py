import hashlib
import sqlite3
import unicodedata
from io import BytesIO
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from markdown_it import MarkdownIt
from werkzeug.utils import secure_filename

from .database import transaction
from .organizer import move_to_trash
from .rules import InputError, civil_day, now_iso, text_value


PHOTO_LIMIT = 3 * 1024 * 1024
PHOTO_COUNT = 4
PHOTO_REQUEST_LIMIT = PHOTO_COUNT * PHOTO_LIMIT + 256 * 1024
MARKDOWN = MarkdownIt("js-default")


def photo_upload(file):
    content = file.stream.read(PHOTO_LIMIT + 1)
    if len(content) > PHOTO_LIMIT:
        raise InputError("Chaque photo doit peser au maximum 3 Mio.", 413)
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime, extension = "image/png", ".png"
    elif content.startswith(b"\xff\xd8\xff"):
        mime, extension = "image/jpeg", ".jpg"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        mime, extension = "image/webp", ".webp"
    else:
        raise InputError("Choisissez des images JPEG, PNG ou WebP.")
    filename = (Path(secure_filename(file.filename or "")).stem[:110] or "photo") + extension
    return filename, mime, hashlib.sha256(content).hexdigest(), content


def found(row, label):
    if row is None:
        raise InputError(f"{label} introuvable.", 404)
    return row


def library_routes(database, json_input, check_found):
    blueprint = Blueprint("library", __name__, url_prefix="/api")

    @blueprint.get("/tasks")
    def tasks():
        with transaction(database) as connection:
            rows = connection.execute(
                """SELECT tasks.*, (SELECT COUNT(*) FROM task_photos WHERE task_id = tasks.id) AS photo_count
                   FROM tasks WHERE deleted_at IS NULL ORDER BY completed_at IS NOT NULL, due IS NULL, due, created_at DESC, id DESC"""
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/tasks/<int:task_id>")
    def task(task_id):
        with transaction(database) as connection:
            row = found(connection.execute("""SELECT tasks.*, courses.title AS course_title
                   FROM tasks LEFT JOIN courses ON courses.id = tasks.course_id AND courses.deleted_at IS NULL
                   WHERE tasks.id = ? AND tasks.deleted_at IS NULL""", (task_id,)).fetchone(), "Tâche")
            photos = connection.execute(
                "SELECT id, filename FROM task_photos WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return {**dict(row), "photos": [dict(photo) for photo in photos]}

    @blueprint.post("/tasks")
    @blueprint.put("/tasks/<int:task_id>")
    def save_task(task_id=None):
        data = json_input()
        due = data.get("due")
        fields = (
            text_value(data, "title", "Titre", length=120, required=True),
            text_value(data, "content", "Détails", length=16000, multiline=True),
            civil_day(due, "Échéance").isoformat() if due not in (None, "") else None,
        )
        course_id = data.get("course_id")
        if course_id is not None and (type(course_id) is not int or not 0 < course_id <= 2**63 - 1):
            raise InputError("Choisissez un cours valide.")
        with transaction(database, write=True) as connection:
            if course_id is not None:
                found(connection.execute(
                    "SELECT id FROM courses WHERE id = ? AND deleted_at IS NULL", (course_id,)
                ).fetchone(), "Cours")
            if task_id is None:
                identifier = connection.execute(
                    "INSERT INTO tasks(title, content, due, created_at, course_id) VALUES (?, ?, ?, ?, ?)", (*fields, now_iso(), course_id)
                ).lastrowid
                return {"id": identifier}, 201
            check_found(connection.execute(
                """UPDATE tasks SET title = ?, content = ?, due = ?,
                   course_id = CASE WHEN ? THEN ? ELSE course_id END WHERE id = ? AND deleted_at IS NULL""",
                (*fields, "course_id" in data, course_id, task_id),
            ), "Tâche")
        return "", 204

    @blueprint.put("/tasks/<int:task_id>/completion")
    def complete_task(task_id):
        completed = request.form.get("completed")
        if completed not in ("true", "false"):
            raise InputError("Indiquez si la tâche est terminée.")
        uploads = [file for file in request.files.getlist("photos") if file.filename]
        if len(uploads) > PHOTO_COUNT or (completed == "false" and uploads):
            raise InputError("Vous pouvez joindre jusqu’à 4 photos à une tâche terminée.")
        photos = [photo_upload(file) for file in uploads]
        with transaction(database, write=True) as connection:
            check_found(connection.execute(
                """UPDATE tasks SET completed_at = CASE WHEN ? THEN COALESCE(completed_at, ?) ELSE NULL END
                   WHERE id = ? AND deleted_at IS NULL""",
                (completed == "true", now_iso(), task_id),
            ), "Tâche")
            connection.executemany(
                """INSERT INTO task_photos(task_id, filename, mime, digest, image) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(task_id, digest) DO NOTHING""",
                [(task_id, *photo) for photo in photos],
            )
            count = connection.execute("SELECT COUNT(*) FROM task_photos WHERE task_id = ?", (task_id,)).fetchone()[0]
            if count > PHOTO_COUNT:
                raise InputError("Cette tâche peut contenir au maximum 4 photos.")
        return "", 204

    @blueprint.delete("/tasks/<int:task_id>")
    def delete_task(task_id):
        with transaction(database, write=True) as connection:
            check_found(move_to_trash(connection, "tasks", task_id), "Tâche")
        return "", 204

    @blueprint.get("/tasks/photos/<int:photo_id>")
    def photo(photo_id):
        with transaction(database) as connection:
            row = found(connection.execute(
                "SELECT filename, mime, image FROM task_photos WHERE id = ? AND task_id IN (SELECT id FROM tasks WHERE deleted_at IS NULL)", (photo_id,)
            ).fetchone(), "Photo")
        return send_file(BytesIO(row["image"]), mimetype=row["mime"], download_name=row["filename"])

    @blueprint.delete("/tasks/photos/<int:photo_id>")
    def delete_photo(photo_id):
        with transaction(database, write=True) as connection:
            check_found(connection.execute("DELETE FROM task_photos WHERE id = ? AND task_id IN (SELECT id FROM tasks WHERE deleted_at IS NULL)", (photo_id,)), "Photo")
        return "", 204

    @blueprint.get("/subjects")
    def subjects():
        with transaction(database) as connection:
            rows = connection.execute(
                """SELECT id, name, (SELECT COUNT(*) FROM courses WHERE subject_id = subjects.id AND deleted_at IS NULL) AS course_count
                   FROM subjects ORDER BY name_key"""
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.post("/subjects")
    @blueprint.put("/subjects/<int:subject_id>")
    def save_subject(subject_id=None):
        name = text_value(json_input(), "name", "Matière", length=80, required=True)
        key = unicodedata.normalize("NFC", name).casefold()
        try:
            with transaction(database, write=True) as connection:
                if subject_id is None:
                    identifier = connection.execute(
                        "INSERT INTO subjects(name, name_key) VALUES (?, ?)", (name, key)
                    ).lastrowid
                    return {"id": identifier}, 201
                check_found(connection.execute(
                    "UPDATE subjects SET name = ?, name_key = ? WHERE id = ?", (name, key, subject_id)
                ), "Matière")
        except sqlite3.IntegrityError as error:
            raise InputError("Cette matière existe déjà.", 409) from error
        return "", 204

    @blueprint.get("/subjects/<int:subject_id>/courses")
    def courses(subject_id):
        with transaction(database) as connection:
            found(connection.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone(), "Matière")
            rows = connection.execute(
                "SELECT id, subject_id, title, updated_at FROM courses WHERE subject_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC, id DESC",
                (subject_id,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/courses")
    def course_picker():
        with transaction(database) as connection:
            rows = connection.execute(
                """SELECT courses.id, courses.title, subjects.name AS subject
                   FROM courses JOIN subjects ON subjects.id = courses.subject_id
                   WHERE courses.deleted_at IS NULL ORDER BY subjects.name_key, courses.title"""
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.post("/courses")
    @blueprint.put("/courses/<int:course_id>")
    def save_course(course_id=None):
        data = json_input()
        subject = data.get("subject")
        if type(subject) is not int or not 0 < subject <= 2**63 - 1:
            raise InputError("Choisissez une matière.")
        fields = (
            subject, text_value(data, "title", "Titre", length=120, required=True),
            text_value(data, "markdown", "Contenu Markdown", length=50000, required=True, multiline=True),
            now_iso(),
        )
        with transaction(database, write=True) as connection:
            found(connection.execute("SELECT id FROM subjects WHERE id = ?", (subject,)).fetchone(), "Matière")
            if course_id is None:
                identifier = connection.execute(
                    "INSERT INTO courses(subject_id, title, markdown, updated_at) VALUES (?, ?, ?, ?)", fields
                ).lastrowid
                return {"id": identifier}, 201
            check_found(connection.execute(
                "UPDATE courses SET subject_id = ?, title = ?, markdown = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (*fields, course_id),
            ), "Cours")
        return "", 204

    @blueprint.get("/courses/<int:course_id>")
    def course(course_id):
        with transaction(database) as connection:
            row = found(connection.execute("SELECT * FROM courses WHERE id = ? AND deleted_at IS NULL", (course_id,)).fetchone(), "Cours")
        return {**dict(row), "html": MARKDOWN.render(row["markdown"])}

    @blueprint.get("/courses/<int:course_id>/source")
    def download_course(course_id):
        with transaction(database) as connection:
            row = found(connection.execute(
                "SELECT title, markdown FROM courses WHERE id = ? AND deleted_at IS NULL", (course_id,)
            ).fetchone(), "Cours")
        filename = (secure_filename(row["title"]) or "cours") + ".md"
        return send_file(BytesIO(row["markdown"].encode()), mimetype="text/markdown", download_name=filename, as_attachment=True)

    @blueprint.delete("/courses/<int:course_id>")
    def delete_course(course_id):
        with transaction(database, write=True) as connection:
            check_found(move_to_trash(connection, "courses", course_id), "Cours")
        return "", 204

    return blueprint
