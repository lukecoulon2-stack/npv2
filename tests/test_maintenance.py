import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from planning.database import initialize
from planning.updates import REQUIRED, apply_pending, fetch_release, pending_revision
from planning.web import create_app


HEADERS = {"X-Tempo-Request": "1"}


class MaintenanceTests(unittest.TestCase):
    def test_visits_and_locked_data(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            first = app.test_client()
            self.assertIn(b'data-welcome="yes"', first.get("/").data)
            self.assertIn(b'data-welcome="no"', first.get("/notes").data)
            self.assertEqual(first.get("/api/maintenance/data").status_code, 401)
            self.assertEqual(first.post("/api/maintenance/unlock", json={"code": "no"}, headers=HEADERS).status_code, 403)
            self.assertEqual(first.post("/api/maintenance/unlock", json={"code": "test-pass"}, headers=HEADERS).status_code, 200)
            self.assertEqual(first.get("/api/maintenance/data").json["notes"], [])
            self.assertIn(b'data-welcome="yes"', app.test_client().get("/").data)
            other_ip = {"REMOTE_ADDR": "192.0.2.2"}
            self.assertIn(b'data-welcome="yes"', first.get("/", environ_overrides=other_ip).data)
            self.assertEqual(first.get("/api/maintenance", environ_overrides=other_ip).status_code, 401)
            logs = first.get("/api/maintenance").json["logs"]
            self.assertEqual([item["visitor_id"] for item in logs], [3, 2, 1, 1])
            self.assertEqual(logs[0]["ip"], "192.0.2.2")
            self.assertEqual(first.post("/api/maintenance/update", headers=HEADERS).status_code, 409)
            first.post("/api/maintenance/lock", headers=HEADERS)
            self.assertEqual(first.get("/api/maintenance").status_code, 401)

    def test_delete_visitor_removes_only_their_history(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            admin, visitor = app.test_client(), app.test_client()
            admin.get("/")
            visitor.get("/")
            visitor.get("/notes")
            path = "/api/maintenance/visitors/2"
            self.assertEqual(visitor.delete(path, headers=HEADERS).status_code, 401)
            admin.post("/api/maintenance/unlock", json={"code": "test-pass"}, headers=HEADERS)
            self.assertEqual(admin.delete(path).status_code, 403)
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 204)
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 404)
            info = admin.get("/api/maintenance").json
            self.assertEqual([row["id"] for row in info["visitors"]], [1])
            self.assertEqual([row["visitor_id"] for row in info["logs"]], [1])
            self.assertIn(b'data-welcome="yes"', visitor.get("/").data)
            self.assertEqual([row["id"] for row in admin.get("/api/maintenance").json["visitors"]], [3, 1])

    def test_data_resets_are_separate_and_keep_event_timezone(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            client = app.test_client()
            path = "/api/maintenance/data"
            self.assertEqual(client.delete(path + "/planning", headers=HEADERS).status_code, 401)
            client.get("/")
            client.post("/api/maintenance/unlock", json={"code": "test-pass"}, headers=HEADERS)
            settings = {
                "name_a": "A", "name_b": "B", "color_a": "#123456", "color_b": "#456789",
                "anchor": "2026-11-23", "first_parent": 1, "timezone": "America/Montreal",
            }
            event = {"title": "Rendez-vous", "day": "2026-11-23", "color": "#123456", "reminder_minutes": 15}
            note = {"title": "Mémo", "content": "Texte", "color": "#123456"}
            self.assertEqual(client.post("/api/settings", json=settings, headers=HEADERS).status_code, 204)
            client.post("/api/notes", json=note, headers=HEADERS)
            client.post("/api/day-notes", json={**note, "author": "A", "day": event["day"]}, headers=HEADERS)
            client.post("/api/events", json=event, headers=HEADERS)
            previous = client.get(path).json["events"][0]["remind_at"]
            self.assertEqual(client.delete(path + "/planning", headers=HEADERS).status_code, 204)
            self.assertEqual(client.get("/api/session").json["timezone"], "America/Montreal")
            client.post("/api/events", json=event, headers=HEADERS)
            raw = client.get(path).json
            self.assertEqual(raw["settings"], [])
            self.assertEqual(raw["day_notes"], [])
            self.assertEqual(len(raw["notes"]), 1)
            self.assertEqual([item["remind_at"] for item in raw["events"]], [previous, previous])
            self.assertEqual(client.delete(path + "/notes", headers=HEADERS).status_code, 204)
            self.assertEqual(len(client.get(path).json["events"]), 2)
            self.assertEqual(client.delete(path + "/events", headers=HEADERS).status_code, 204)
            self.assertEqual(client.get(path).json["events"], [])
            self.assertEqual(client.delete(path + "/visitors", headers=HEADERS).status_code, 404)


class UpdaterTests(unittest.TestCase):
    def test_stage_then_install_without_local_configuration_or_data(self):
        with TemporaryDirectory() as workspace:
            remote, project = (Path(workspace) / name for name in ("remote", "project"))
            remote.mkdir()
            project.mkdir()
            for path in REQUIRED:
                (remote / path).parent.mkdir(exist_ok=True, parents=True)
                (remote / path).write_text("# Nouvelle version\n")
            (remote / "planning_config_starter.json").write_text("remplacement")
            (remote / "planning" / "archive.sqlite3").write_text("remplacement")
            config = project / "planning_config_starter.json"
            config.write_text("configuration locale")
            server_data = Path(workspace) / "data.sqlite3"
            server_data.write_text("données locales")
            subprocess.run(["git", "init", "-q", str(remote)], check=True)
            subprocess.run(["git", "-C", str(remote), "add", "."], check=True)
            subprocess.run([
                "git", "-C", str(remote), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                "commit", "-qm", "Release",
            ], check=True)
            with patch("planning.updates.REPOSITORY", remote.as_uri()):
                revision = fetch_release(project)
                self.assertEqual(pending_revision(project), revision)
                self.assertFalse((project / "start.py").exists())
                self.assertEqual(apply_pending(project), revision)
                self.assertIsNone(fetch_release(project))
            self.assertEqual((project / "start.py").read_text(), "# Nouvelle version\n")
            self.assertEqual(config.read_text(), "configuration locale")
            self.assertEqual(server_data.read_text(), "données locales")
            self.assertFalse((project / "planning/archive.sqlite3").exists())
