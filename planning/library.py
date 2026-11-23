import hashlib
import sqlite3
import unicodedata
from io import BytesIO
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_file
from markdown_it import MarkdownIt
from werkzeug.utils import secure_filename

from .accounts import account_transaction
from .course_markdown import COURSE_FIELDS, split_course_markdown
from .organizer import move_to_trash
from .rules import InputError, civil_day, now_iso, text_value


PHOTO_LIMIT = 3 * 1024 * 1024
PHOTO_COUNT = 4
PHOTO_REQUEST_LIMIT = PHOTO_COUNT * PHOTO_LIMIT + 256 * 1024
MARKDOWN = MarkdownIt("js-default")


def prepare_course_markdown(data):
    raw_markdown = text_value(data, "markdown", "Contenu Markdown", length=50000, required=True, multiline=True)
    metadata, markdown = split_course_markdown(raw_markdown)
    if not markdown.strip():
        raise InputError("Ajoutez le contenu du cours après le bloc d’informations.")
    return metadata, markdown


def subject_key(name):
    return unicodedata.normalize("NFC", name).casefold()


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
        with account_transaction(database) as connection:
            rows = connection.execute(
                """SELECT tasks.*, (SELECT COUNT(*) FROM task_photos WHERE task_id = tasks.id) AS photo_count
                   FROM tasks WHERE workspace_id = ? AND deleted_at IS NULL
                   ORDER BY completed_at IS NOT NULL, due IS NULL, due, created_at DESC, id DESC""", (g.workspace,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/tasks/<int:task_id>")
    def task(task_id):
        with account_transaction(database) as connection:
            row = found(connection.execute("""SELECT tasks.*, courses.title AS course_title
                   FROM tasks LEFT JOIN courses ON courses.id = tasks.course_id AND courses.deleted_at IS NULL
                   WHERE tasks.id = ? AND tasks.workspace_id = ? AND tasks.deleted_at IS NULL""",
                (task_id, g.workspace),
            ).fetchone(), "Tâche")
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
        with account_transaction(database, write=True) as connection:
            if course_id is not None:
                found(connection.execute(
                    "SELECT id FROM courses WHERE id = ? AND deleted_at IS NULL", (course_id,)
                ).fetchone(), "Cours")
            if task_id is None:
                identifier = connection.execute(
                    "INSERT INTO tasks(title, content, due, created_at, course_id, workspace_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (*fields, now_iso(), course_id, g.workspace),
                ).lastrowid
                return {"id": identifier}, 201
            check_found(connection.execute(
                """UPDATE tasks SET title = ?, content = ?, due = ?,
                   course_id = CASE WHEN ? THEN ? ELSE course_id END
                   WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL""",+                (*fields, "course_id" in data, course_id, task_id, g.workspace),
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
        with account_transaction(database, write=True) as connection:
            check_found(connection.execute(
                """UPDATE tasks SET completed_at = CASE WHEN ? THEN COALESCE(completed_at, ?) ELSE NULL END
                   WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL""",
                (completed == "true", now_iso(), task_id, g.workspace),
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
        with account_transaction(database, write=True) as connection:
            check_found(move_to_trash(connection, "tasks", task_id), "Tâche")
        return "", 204

    @blueprint.get("/tasks/photos/<int:photo_id>")
    def photo(photo_id):
        with account_transaction(database) as connection:
            row = found(connection.execute(
                """SELECT filename, mime, image FROM task_photos WHERE id = ? AND task_id IN (
                       SELECT id FROM tasks WHERE workspace_id = ? AND deleted_at IS NULL
                   )""", (photo_id, g.workspace),
            ).fetchone(), "Photo")
        return send_file(BytesIO(row["image"]), mimetype=row["mime"], download_name=row["filename"])

    @blueprint.delete("/tasks/photos/<int:photo_id>")
    def delete_photo(photo_id):
        with account_transaction(database, write=True) as connection:
            check_found(connection.execute(
                """DELETE FROM task_photos WHERE id = ? AND task_id IN (
                       SELECT id FROM tasks WHERE workspace_id = ? AND deleted_at IS NULL
                   )""", (photo_id, g.workspace),
            ), "Photo")
        return "", 204

    @blueprint.get("/subjects")
    def subjects():
        with account_transaction(database) as connection:
            rows = connection.execute(
                """SELECT id, name, (SELECT COUNT(*) FROM courses WHERE subject_id = subjects.id AND deleted_at IS NULL) AS course_count
                   FROM subjects ORDER BY name_key"""
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.post("/subjects")
    @blueprint.put("/subjects/<int:subject_id>")
    def save_subject(subject_id=None):
        name = text_value(json_input(), "name", "Matière", length=80, required=True)
        key = subject_key(name)
        try:
            with account_transaction(database, write=True, course_files=subject_id is not None) as connection:
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
        with account_transaction(database) as connection:
            found(connection.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone(), "Matière")
            rows = connection.execute(
                """SELECT id, subject_id, title, theme, level, difficulty, added_at, updated_at
                   FROM courses WHERE subject_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC, id DESC""",
                (subject_id,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/courses")
    def course_picker():
        with account_transaction(database) as connection:
            rows = connection.execute(
                """SELECT courses.id, courses.title, courses.subject_id, subjects.name AS subject,
                          courses.level, courses.theme, courses.difficulty
                   FROM courses JOIN subjects ON subjects.id = courses.subject_id
                   WHERE courses.deleted_at IS NULL ORDER BY subjects.name_key, courses.title"""
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.post("/courses/import")
    def import_course():
        metadata, markdown = prepare_course_markdown(json_input())
        return {"metadata": metadata, "markdown": markdown}

    @blueprint.post("/courses")
    @blueprint.put("/courses/<int:course_id>")
    def save_course(course_id=None):
        data = json_input()
        detected, markdown = prepare_course_markdown(data)
        data = {**detected, **data}
        subject = data.get("subject")
        subject_name = text_value(data, "subject", "Matière", length=80, required=True) if isinstance(subject, str) else None
        if subject_name is None and (type(subject) is not int or not 0 < subject <= 2**63 - 1):
            raise InputError("Choisissez une matière.")
        title = text_value(data, "title", "Nom du cours", length=120, required=True)
        stamp = now_iso()
        required = course_id is None and subject_name is not None
        metadata = tuple(
            text_value(data, name, label, length=length, required=required) if required or name in data else None
            for name, label, length in COURSE_FIELDS
        )
        with account_transaction(database, write=True, course_files=True) as connection:
            if subject_name is not None:
                key = subject_key(subject_name)
                connection.execute(
                    "INSERT INTO subjects(name, name_key) VALUES (?, ?) ON CONFLICT(name_key) DO NOTHING",
                    (subject_name, key),
                )
                subject = connection.execute("SELECT id FROM subjects WHERE name_key = ?", (key,)).fetchone()["id"]
            else:
                found(connection.execute("SELECT id FROM subjects WHERE id = ?", (subject,)).fetchone(), "Matière")
            if course_id is None:
                identifier = connection.execute(
                    """INSERT INTO courses(subject_id, title, markdown, updated_at, added_at, theme, level, difficulty)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (subject, title, markdown, stamp, stamp, *(value or "" for value in metadata)),
                ).lastrowid
                return {"id": identifier, "subject_id": subject}, 201
            check_found(connection.execute(
                """UPDATE courses SET subject_id = ?, title = ?, markdown = ?, updated_at = ?,
                   theme = COALESCE(?, theme), level = COALESCE(?, level), difficulty = COALESCE(?, difficulty)
                   WHERE id = ? AND deleted_at IS NULL""",
                (subject, title, markdown, stamp, *metadata, course_id),
            ), "Cours")
        if subject_name is not None:
            return {"id": course_id, "subject_id": subject}
        return "", 204

    @blueprint.get("/courses/<int:course_id>")
    def course(course_id):
        with account_transaction(database) as connection:
            row = found(connection.execute(
                """SELECT courses.*, subjects.name AS subject FROM courses JOIN subjects ON subjects.id = subject_id
                   WHERE courses.id = ? AND deleted_at IS NULL""", (course_id,),
            ).fetchone(), "Cours")
        return {**dict(row), "html": MARKDOWN.render(row["markdown"])}

    @blueprint.get("/courses/<int:course_id>/source")
    def download_course(course_id):
        with account_transaction(database) as connection:
            row = found(connection.execute(
                "SELECT title, markdown FROM courses WHERE id = ? AND deleted_at IS NULL", (course_id,)
            ).fetchone(), "Cours")
        filename = (secure_filename(row["title"]) or "cours") + ".md"
        return send_file(BytesIO(row["markdown"].encode()), mimetype="text/markdown", download_name=filename, as_attachment=True)

    @blueprint.delete("/courses/<int:course_id>")
    def delete_course(course_id):
        with account_transaction(database, write=True, course_files=True) as connection:
            check_found(move_to_trash(connection, "courses", course_id), "Cours")
        return "", 204

    return blueprint
