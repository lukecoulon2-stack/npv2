import base64
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from planning.database import initialize
from planning.web import create_app


WRITE = {"X-Tempo-Request": "1"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3e8AAAAASUVORK5CYII="
)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        database = Path(workspace.name) / "planning.sqlite3"
        initialize(database)
        self.client = create_app(database, "bench").test_client()

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
