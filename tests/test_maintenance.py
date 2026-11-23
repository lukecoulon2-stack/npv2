import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from planning.database import initialize
from planning.updates import REQUIRED, apply_pending, fetch_release, pending_revision
from planning.visits import DEVICE_COOKIE
from planning.web import create_app


HEADERS = {"X-Tempo-Request": "1"}
PASSWORD = "un-mot-de-passe-de-test"


class MaintenanceTests(unittest.TestCase):
    def register(self, client, username="maintenance", *, share=True):
        self.assertEqual(client.post("/api/account/register", json={
            "username": username, "password": PASSWORD,
        }, headers=HEADERS).status_code, 204)
        if share:
            self.assertEqual(client.post("/api/account/share", headers=HEADERS).status_code, 204)

    def test_visits_and_locked_data(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            first = app.test_client()
            self.assertIn(b'data-welcome="yes"', first.get("/").data)
            self.assertIn(b'data-welcome="no"', first.get("/notes").data)
            self.assertEqual(first.get("/api/maintenance/data").status_code, 401)
            self.register(first)
            self.assertEqual(first.post("/api/maintenance/unlock", json={"code": "no"}, headers=HEADERS).status_code, 403)
            self.assertEqual(first.post("/api/maintenance/unlock", json={"code": "test-pass"}, headers=HEADERS).status_code, 200)
            self.assertEqual(first.get("/api/maintenance/data").json["notes"], [])
            self.assertIn(b'data-welcome="yes"', app.test_client().get("/").data)
            other_ip = {"REMOTE_ADDR": "192.0.2.2"}
            self.assertIn(b'data-welcome="yes"', first.get("/", environ_overrides=other_ip).data)
            self.assertEqual(first.get("/api/maintenance", environ_overrides=other_ip).status_code, 401)
            overview = first.get("/api/maintenance").json
            logs = overview["logs"]
            self.assertEqual([item["visitor_id"] for item in logs], [4, 3, 2, 1, 1])
            self.assertEqual([item["username"] for item in logs], ["maintenance", None, "maintenance", None, None])
            self.assertEqual(logs[0]["ip"], "192.0.2.2")
            self.assertEqual(overview["accounts"], [{"id": 1, "username": "maintenance", "visitor_count": 2}])
            visitors = first.get("/api/maintenance/accounts/1").json["visitors"]
            self.assertEqual([item["id"] for item in visitors], [4, 2])
            self.assertEqual(visitors[0]["last_connected_at"], logs[0]["connected_at"])
            self.assertEqual(first.post("/api/maintenance/update", headers=HEADERS).status_code, 409)
            first.post("/api/maintenance/lock", headers=HEADERS)
            self.assertEqual(first.get("/api/maintenance").status_code, 401)

    def test_delete_visitor_removes_only_their_history(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            admin, visitor, second_browser = (app.test_client() for _ in range(3))
            admin.get("/")
            self.register(admin)
            visitor.set_cookie(DEVICE_COOKIE, admin.get_cookie(DEVICE_COOKIE).value)
            self.register(visitor, "alexandra")
            second_browser.post("/api/account/login", json={"username": "alexandra", "password": PASSWORD}, headers=HEADERS)
            path = "/api/maintenance/accounts/2/visitors/3"
            self.assertEqual(visitor.delete(path, headers=HEADERS).status_code, 401)
            admin.post("/api/maintenance/unlock", json={"code": "test-pass"}, headers=HEADERS)
            self.assertEqual(admin.delete("/api/maintenance/accounts/2/visitors/2", headers=HEADERS).status_code, 404)
            self.assertEqual(admin.delete(path).status_code, 403)
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 204)
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 404)
            info = admin.get("/api/maintenance").json
            self.assertEqual([row["visitor_count"] for row in info["accounts"]], [1, 1])
            self.assertEqual([row["visitor_id"] for row in info["logs"]], [4, 2, 1])
            self.assertEqual(visitor.get("/api/session").status_code, 200)
            self.assertIn(b'data-welcome="yes"', visitor.get("/").data)
            linked = admin.get("/api/maintenance/accounts/2").json["visitors"]
            self.assertEqual([row["id"] for row in linked], [5, 4])

    def test_delete_account_revokes_logins_and_preserves_its_shared_session(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            admin, owner, second_browser, guest, newcomer = (app.test_client() for _ in range(5))
            self.register(admin)
            self.register(owner, "titulaire")
            self.register(guest, "invite", share=False)
            credentials = {"username": "titulaire", "password": PASSWORD}
            self.assertEqual(second_browser.post("/api/account/login", json=credentials, headers=HEADERS).status_code, 204)
            code = owner.get("/api/session").json["account"]["code"]
            self.assertEqual(guest.post("/api/account/join", json={"code": code}, headers=HEADERS).status_code, 204)
            note = {"title": "Mémo partagé", "content": "Texte", "color": "#123456"}
            self.assertEqual(owner.post("/api/notes", json=note, headers=HEADERS).status_code, 201)
            path = "/api/maintenance/accounts/2"
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 401)
            admin.post("/api/maintenance/unlock", json={"code": "test-pass"}, headers=HEADERS)
            self.assertEqual(len(admin.get(path).json["visitors"]), 2)
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 204)
            self.assertEqual(admin.get(path).status_code, 404)
            self.assertEqual(admin.delete(path, headers=HEADERS).status_code, 404)
            self.assertEqual(owner.get("/api/session").status_code, 401)
            self.assertEqual(second_browser.get("/api/session").status_code, 401)
            self.assertEqual(owner.post("/api/account/login", json=credentials, headers=HEADERS).status_code, 401)
            self.assertNotIn(2, [entry["account_id"] for entry in admin.get("/api/maintenance").json["logs"]])
            self.assertEqual(guest.get("/api/notes").json[0]["title"], "Mémo partagé")
            self.assertIsNone(guest.get("/api/session").json["account"]["owner"])
            self.register(newcomer, "titulaire", share=False)
            self.assertEqual(newcomer.post("/api/account/join", json={"code": code}, headers=HEADERS).status_code, 204)
            self.assertEqual(newcomer.get("/api/notes").json[0]["title"], "Mémo partagé")
            self.assertEqual(admin.get("/api/maintenance/accounts/4").json["username"], "titulaire")

            self.assertTrue(admin.get("/api/maintenance/accounts/1").json["is_current"])
            self.assertEqual(admin.delete("/api/maintenance/accounts/1", headers=HEADERS).status_code, 204)
            self.assertEqual(admin.get("/api/session").status_code, 401)

    def test_data_resets_are_separate_and_keep_event_timezone(self):
        with TemporaryDirectory() as workspace, patch.dict(os.environ, {"NAONING_MAINTENANCE_CODE": "test-pass"}):
            database = Path(workspace) / "planning.sqlite3"
            initialize(database)
            app = create_app(database, "bench")
            client = app.test_client()
            path = "/api/maintenance/data"
            self.assertEqual(client.delete(path + "/planning", headers=HEADERS).status_code, 401)
            client.get("/")
            self.register(client)
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
