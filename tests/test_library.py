import base64
import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from planning.database import APPLICATION_ID, MIGRATIONS, initialize, transaction
from planning.web import create_app


WRITE = {"X-Tempo-Request": "1"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3e8AAAAASUVORK5CYII="
)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.database = Path(workspace.name) / "planning.sqlite3"
        initialize(self.database)
        self.client = create_app(self.database, "bench").test_client()
        self.assertEqual(self.write("/api/account/register", {
            "username": "bibliotheque", "password": "un-mot-de-passe-de-test",
        }).status_code, 204)
        self.assertEqual(self.write("/api/account/share", None).status_code, 204)

    def write(self, path, data, method="POST"):
        return self.client.open(path, method=method, json=data, headers=WRITE)

    def test_complete_task_with_photo_persists_and_retries_are_safe(self):
        response = self.write("/api/tasks", {"title": "Travaux", "due": "2026-12-25", "content": "Préparer le matériel"})
        self.assertEqual(response.status_code, 201)
        path = f"/api/tasks/{response.json['id']}"
        for _ in range(2):
            response = self.client.put(path + "/completion", headers=WRITE, data={
                "completed": "true", "photos": (BytesIO(PNG), "photo.png"),
            })
            self.assertEqual(response.status_code, 204)
        task = self.client.get(path).json
        self.assertIsNotNone(task["completed_at"])
        self.assertEqual(len(task["photos"]), 1)
        photo = f"/api/tasks/photos/{task['photos'][0]['id']}"
        response = self.client.get(photo)
        self.assertEqual(response.mimetype, "image/png")
        self.assertEqual(response.data, PNG)
        self.client.put(path + "/completion", headers=WRITE, data={"completed": "false"})
        self.assertIsNone(self.client.get(path).json["completed_at"])
        self.assertEqual(self.client.delete(path, headers=WRITE).status_code, 204)
        self.assertEqual(self.client.get(photo).status_code, 404)

    def test_invalid_photo_leaves_task_pending(self):
        task = self.write("/api/tasks", {"title": "Travaux"}).json
        path = f"/api/tasks/{task['id']}"
        response = self.client.put(path + "/completion", headers=WRITE, data={
            "completed": "true", "photos": (BytesIO(b"<svg></svg>"), "photo.png"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.client.get(path).json["completed_at"])

    def test_courses_are_grouped_downloadable_and_html_is_escaped(self):
        subject = self.write("/api/subjects", {"name": "Histoire"}).json["id"]
        other = self.write("/api/subjects", {"name": "Français"}).json["id"]
        self.assertEqual(self.write("/api/subjects", {"name": "HISTOIRE"}).status_code, 409)
        content = "# Leçon\n\n**Important**\n\n<script>alert(1)</script>"
        course = {"title": "Histoire", "subject": subject, "markdown": content}
        saved = self.write("/api/courses", course)
        self.assertEqual(saved.status_code, 201)
        identifier = saved.json["id"]
        path = f"/api/courses/{identifier}"
        self.assertEqual([record["id"] for record in self.client.get(f"/api/subjects/{subject}/courses").json], [identifier])
        self.assertEqual(self.client.get(f"/api/subjects/{other}/courses").json, [])
        rendered = self.client.get(path).json["html"]
        self.assertIn("<strong>Important</strong>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        response = self.client.get(path + "/source")
        self.assertEqual(response.data.decode(), content)
        self.assertIn(".md", response.headers["Content-Disposition"])
        self.assertEqual(self.write(path, {**course, "subject": other}, "PUT").status_code, 204)
        self.assertEqual(self.client.get(f"/api/subjects/{subject}/courses").json, [])
        self.assertEqual(len(self.client.get(f"/api/subjects/{other}/courses").json), 1)

    def test_revision_link_and_search_survive_trash_restore(self):
        subject = self.write("/api/subjects", {"name": "Géographie"}).json["id"]
        course = self.write("/api/courses", {
            "subject": subject, "title": "Océans", "markdown": "Répartition des continents",
        }).json["id"]
        task = self.write("/api/tasks", {"title": "Réviser les océans", "course_id": course}).json["id"]
        task_path = f"/api/tasks/{task}"
        course_path = f"/api/courses/{course}"
        self.assertEqual(self.client.get(task_path).json["course_title"], "Océans")
        self.assertEqual([row["kind"] for row in self.client.get("/api/search?q=oceans").json], ["courses", "tasks"])
        self.assertEqual(self.client.get("/api/search?q=repartition+continents&type=courses").json[0]["id"], course)
        self.assertEqual(self.client.delete(course_path, headers=WRITE).status_code, 204)
        self.assertIsNone(self.client.get(task_path).json["course_title"])
        self.assertEqual(self.client.get("/api/search?q=oceans&type=courses").json, [])
        self.assertEqual(self.client.post(f"/api/trash/courses/{course}", headers=WRITE).status_code, 204)
        self.assertEqual(self.client.get(task_path).json["course_title"], "Océans")
        self.client.delete(course_path, headers=WRITE)
        self.assertEqual(self.client.delete(f"/api/trash/courses/{course}", headers=WRITE).status_code, 204)
        self.assertIsNone(self.client.get(task_path).json["course_id"])

    def test_import_creates_numbered_markdown_and_updates_the_catalog(self):
        course = {
            "subject": "Physique", "title": "Électricité", "theme": "Circuits", "level": "4e",
            "difficulty": "Intermédiaire", "markdown": "# Électricité\r\n\r\nLe courant.\r\n",
        }
        self.assertEqual(self.write("/api/courses", {**course, "level": ""}).status_code, 400)
        self.assertEqual(self.client.get("/api/subjects").json, [])
        directory = self.database.parent / "cours"
        index = directory / "index.json"
        backup_index = index.rename(directory / "index.backup")
        index.mkdir()
        with self.assertLogs(self.client.application.logger, "ERROR"):
            self.assertEqual(self.write("/api/courses", course).status_code, 503)
        self.assertEqual(list(directory.glob("*.md")), [])
        self.assertEqual(self.client.get("/api/subjects").json, [])
        index.rmdir()
        backup_index.rename(index)

        published = self.write("/api/courses", course)
        self.assertEqual(published.status_code, 201)
        identifier, subject = (published.json[name] for name in ("id", "subject_id"))
        path = f"/api/courses/{identifier}"
        source = directory / f"{identifier}.md"

        def info():
            return json.loads(index.read_text(encoding="utf-8"))[str(identifier)]

        added_at = self.client.get(path).json["added_at"]
        self.assertTrue(added_at)
        self.assertEqual(info(), {
            "id": identifier, "fichier": source.name, "nom": "Électricité", "matiere": "Physique", "theme": "Circuits",
            "niveau": "4e", "date_ajout": added_at, "difficulte": "Intermédiaire", "supprime_le": None,
        })
        self.assertEqual(source.read_bytes(), course["markdown"].encode())
        self.assertEqual(self.client.get(path + "/source").data, source.read_bytes())
        self.assertEqual(self.client.get("/api/search?q=circuits").json[0]["id"], identifier)
        self.assertEqual(self.write(f"/api/subjects/{subject}", {"name": "Sciences"}, "PUT").status_code, 204)
        self.assertEqual(info()["matiere"], "Sciences")
        updated = self.write(path, {**course, "subject": "SCIENCES", "markdown": "# Révision", "difficulty": "Facile"}, "PUT")
        self.assertEqual(updated.json["subject_id"], subject)
        self.assertEqual(info()["date_ajout"], added_at)
        self.assertEqual(info()["difficulte"], "Facile")
        self.assertEqual(source.read_text(encoding="utf-8"), "# Révision")

        trash = f"/api/trash/courses/{identifier}"
        self.assertEqual(self.client.delete(path, headers=WRITE).status_code, 204)
        self.assertTrue(info()["supprime_le"])
        self.assertTrue(source.is_file())
        self.assertEqual(self.client.post(trash, headers=WRITE).status_code, 204)
        self.assertIsNone(info()["supprime_le"])
        self.client.delete(path, headers=WRITE)
        self.assertEqual(self.client.delete(trash, headers=WRITE).status_code, 204)
        self.assertFalse(source.exists())
        self.assertEqual(json.loads(index.read_text(encoding="utf-8")), {})

    def test_course_metadata_is_extracted_without_publishing_the_block(self):
        title = "Démocraties fragilisées et expériences totalitaires dans l'Europe de l'entre-deux-guerres"
        theme = "L'Europe, un théâtre majeur des guerres totales (1914-1945)"
        header = f"## -- INFO SUR LE COURS : matiere : Histoire cours : {title} niveau : 3e (Cycle 4) theme : {theme} difficulté : intermédiaire"
        body = "-- ORGANISATION :\r\n1 : Introduction\r\n\r\n-- PARTIE 1 :\r\nTexte du cours.\r\n"
        raw = f"{header}\r\n--\r\n\r\n{body}"
        fields = {"subject": "Histoire", "title": title, "level": "3e (Cycle 4)", "theme": theme, "difficulty": "intermédiaire"}
        prepared = self.write("/api/courses/import", {"markdown": raw})
        self.assertEqual(prepared.json, {"metadata": fields, "markdown": body})
        self.assertEqual(self.write("/api/courses/import", {"markdown": header}).status_code, 400)
        published = self.write("/api/courses", {"markdown": raw})
        self.assertEqual(published.status_code, 201)
        identifier = published.json["id"]
        url = f"/api/courses/{identifier}"
        course = self.client.get(url).json
        self.assertEqual(course["markdown"], body)
        self.assertIn("Texte du cours", course["html"])
        self.assertNotIn("INFO SUR LE COURS", course["html"])
        self.assertEqual(self.client.get(f"{url}/source").data, body.encode())
        directory = self.database.parent / "cours"
        self.assertEqual((directory / f"{identifier}.md").read_bytes(), body.encode())
        entry = json.loads((directory / "index.json").read_text())[str(identifier)]
        self.assertEqual([entry[key] for key in ("nom", "matiere", "niveau", "theme", "difficulte")], [
            title, "Histoire", "3e (Cycle 4)", theme, "intermédiaire",
        ])

        example = "## Exemple\n\n```md\n## -- INFO SUR LE COURS : matiere : Histoire\n```\n"
        updated = self.write(url, {**fields, "title": "Titre corrigé", "markdown": raw.replace(body, example)}, "PUT")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get(url).json["title"], "Titre corrigé")
        self.assertEqual(self.client.get(url).json["markdown"], example)

    def test_migration_rebuilds_the_files_for_a_previous_course(self):
        with TemporaryDirectory() as workspace:
            database = Path(workspace) / "legacy.sqlite3"
            with transaction(database, write=True) as connection:
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                for version, migration in enumerate(MIGRATIONS[:8], start=1):
                    for statement in migration:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version = {version}")
                connection.execute("INSERT INTO subjects VALUES (1, 'Histoire', 'histoire')")
                connection.execute(
                    """INSERT INTO courses(id, subject_id, title, markdown, updated_at)
                       VALUES (42, 1, 'Chronologie', ?, '2026-11-23T12:00:00+00:00')""",
                    ("-- INFO SUR LE COURS :\nMatière : Histoire\nCours : Chronologie\nNiveau : 3e\n--\n\n# Chronologie",),
                )
            initialize(database)
            directory = database.parent / "cours"
            self.assertEqual((directory / "42.md").read_text(), "# Chronologie")
            info = json.loads((directory / "index.json").read_text())["42"]
            self.assertEqual(info["date_ajout"], "2026-11-23T12:00:00+00:00")
            self.assertEqual(info["niveau"], "3e")
