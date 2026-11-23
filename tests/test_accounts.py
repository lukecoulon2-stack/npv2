import base64
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from planning.accounts import LOGIN_COOKIE, claim_existing
from planning.database import APPLICATION_ID, MIGRATIONS, initialize, transaction
from planning.web import create_app

HEADERS = {"X-Tempo-Request": "1"}
PASSWORD = "un-mot-de-passe-de-test"
NOTE = {"title": "Note privée", "content": "Contenu de la note", "color": "#aa3355"}
PARENTS = {
    "name_a": "Anaëlle", "color_a": "#8f5cd8", "name_b": "Bastien", "color_b": "#358eaf",
    "anchor": "2026-12-30", "first_parent": 1, "timezone": "Europe/Paris",
}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3e8AAAAASUVORK5CYII=")


class AccountTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.database = Path(work.name) / "planning.sqlite3"
        self.app = create_app(self.database, "normal")

    def write(self, client, route, data=None, *, method="POST", headers=HEADERS):
        return client.open(f"/api{route}", method=method, json=data, headers=headers)

    def register(self, client, username):
        return self.write(client, "/account/register", {"username": username, "password": PASSWORD})

    def test_account_cookie_survives_restart_and_can_be_revoked(self):
        initialize(self.database)
        client = self.app.test_client()
        self.assertIn(b"data-account-form", client.get("/notes").data)
        self.assertEqual(client.get("/api/notes").status_code, 401)
        self.assertEqual(client.get("/api/courses").status_code, 401)
        self.assertEqual(self.write(client, "/account/share").status_code, 401)

        created = self.register(client, "Camille")
        self.assertEqual(created.status_code, 204)
        self.assertIn("HttpOnly", created.headers["Set-Cookie"])
        self.assertIn("Max-Age=2592000", created.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", created.headers["Set-Cookie"])
        token = client.get_cookie(LOGIN_COOKIE).value
        self.assertNotIn(PASSWORD, created.headers["Set-Cookie"])
        with transaction(self.database) as connection:
            self.assertNotEqual(connection.execute("SELECT password_hash FROM accounts").fetchone()[0], PASSWORD)
            self.assertNotEqual(connection.execute("SELECT token_hash FROM account_logins").fetchone()[0], token)

        restarted = create_app(self.database, "normal").test_client()
        restarted.set_cookie(LOGIN_COOKIE, token)
        self.assertEqual(restarted.get("/api/session").json["account"]["username"], "Camille")
        self.assertNotIn(b"data-account-form", restarted.get("/notes").data)
        self.assertEqual(self.register(restarted, "CAMILLE").status_code, 409)
        self.assertEqual(self.write(restarted, "/account/logout").status_code, 204)
        self.assertEqual(client.get("/api/session").status_code, 401)
        self.assertEqual(self.write(client, "/account/login", {"username": "Camille", "password": "mauvais-mdp"}).status_code, 401)
        self.assertEqual(self.write(client, "/account/login", {"username": "camille", "password": PASSWORD}).status_code, 204)

    def test_private_data_shared_session_and_common_courses(self):
        initialize(self.database)
        host, guest, other = (self.app.test_client() for _ in range(3))
        self.assertEqual(self.register(host, "parent-a").status_code, 204)
        self.assertEqual(self.register(guest, "parent-b").status_code, 204)
        self.assertEqual(self.register(other, "autre-compte").status_code, 204)
        self.assertFalse(guest.get("/api/session").json["account"]["session_active"])
        self.assertIn(b"data-session-choice", guest.get("/cours").data)
        self.assertNotIn(b"Navigation principale", guest.get("/planning").data)
        for route in ("notes", "tasks", "courses", "maintenance/data", "trash"):
            self.assertEqual(guest.get(f"/api/{route}").status_code, 403)
        self.assertEqual(self.write(guest, "/settings", PARENTS).status_code, 403)
        self.assertEqual(self.write(host, "/account/share").status_code, 204)
        self.assertEqual(self.write(other, "/account/share").status_code, 204)
        self.assertEqual(self.write(host, "/settings", PARENTS).status_code, 204)
        self.assertEqual(self.write(other, "/settings", {**PARENTS, "name_a": "Autre parent"}).status_code, 204)
        self.assertEqual(self.write(host, "/weekends/2026", {"enabled": True}, method="PUT").status_code, 204)
        self.assertEqual(other.get("/api/weekends").json, [])
        self.assertEqual(self.write(host, "/day-notes", {"day": "2026-12-25", "author": "Parent", "content": "Test"}).status_code, 201)
        self.assertEqual(other.get("/api/day-notes?day=2026-12-25").json, [])

        note_id = self.write(host, "/notes", NOTE).json["id"]
        self.assertEqual(self.write(other, f"/notes/{note_id}", NOTE, method="PUT").status_code, 404)
        self.assertEqual(other.get("/api/search?q=privée").json, [])
        event_id = self.write(host, "/events", {"title": "RDV", "day": "2026-12-25", "color": "#aa3355"}).json["id"]
        self.assertEqual(other.get(f"/api/events/{event_id}").status_code, 404)
        subject_id = self.write(host, "/subjects", {"name": "Histoire"}).json["id"]
        course_id = self.write(host, "/courses", {"title": "Leçon", "subject": subject_id, "markdown": "# Histoire"}).json["id"]
        self.assertEqual(other.get(f"/api/courses/{course_id}").json["title"], "Leçon")
        task_id = self.write(host, "/tasks", {"title": "Réviser", "course_id": course_id}).json["id"]
        self.assertEqual(host.put(f"/api/tasks/{task_id}/completion", headers=HEADERS, data={
            "completed": "true", "photos": (BytesIO(PNG), "photo.png"),
        }).status_code, 204)
        photo_id = host.get(f"/api/tasks/{task_id}").json["photos"][0]["id"]
        self.assertEqual(other.get(f"/api/tasks/photos/{photo_id}").status_code, 404)
        self.assertEqual(self.write(other, f"/tasks/photos/{photo_id}", method="DELETE").status_code, 404)

        self.assertEqual(self.write(host, "/account/share").status_code, 204)
        code = host.get("/api/session").json["account"]["code"]
        self.assertRegex(code, r"^[A-Z2-9]{8}$")
        self.assertEqual(self.write(host, "/account/share").status_code, 204)
        self.assertEqual(host.get("/api/session").json["account"]["code"], code)
        guest_context = guest.get("/reglages").data.split(b'data-account="', 1)[1].split(b'"', 1)[0].decode()
        self.assertEqual(self.write(guest, "/account/join", {"code": code.lower()}).status_code, 204)
        self.assertEqual(guest.get("/api/notes", headers={"X-Tempo-Account": guest_context}).status_code, 409)
        session = guest.get("/api/session").json
        self.assertEqual(session["account"], {
            "username": "parent-b", "owner": "parent-a", "personal": False, "code": None,
            "site_name": "Planneli", "session_active": True,
        })
        self.assertEqual(session["settings"]["name_a"], PARENTS["name_a"])
        self.assertEqual(guest.get(f"/api/tasks/photos/{photo_id}").data, PNG)
        self.assertEqual(self.write(guest, f"/notes/{note_id}", method="DELETE").status_code, 204)
        self.assertEqual(host.get("/api/trash").json[0]["id"], note_id)

        self.assertEqual(self.write(guest, "/account/leave").status_code, 204)
        self.assertEqual(guest.get("/api/trash").status_code, 403)
        self.assertEqual(self.write(guest, f"/trash/notes/{note_id}").status_code, 403)
        self.assertEqual(self.write(host, "/account/leave").status_code, 409)
        self.assertEqual(self.write(host, "/account/share", method="DELETE").status_code, 405)
        self.assertEqual(self.write(other, "/account/join", {"code": code}).status_code, 409)
        self.assertEqual(self.write(guest, "/account/join", {"code": code}).status_code, 204)
        self.assertEqual(guest.get(f"/api/courses/{course_id}").status_code, 200)

        self.assertEqual(self.write(guest, "/account/site-name", {"name": "Chez Camille"}, method="PUT").status_code, 204)
        self.assertIn(b"Chez Camille", guest.get("/reglages").data)
        self.assertEqual(host.get("/api/session").json["account"]["site_name"], "Planneli")
        self.assertEqual(self.write(guest, "/account/site-name", {"name": ""}, method="PUT").status_code, 204)
        self.assertEqual(guest.get("/api/session").json["account"]["site_name"], "Planneli")

    def test_activity_logs_use_account_id_time_and_action_without_payloads(self):
        initialize(self.database)
        client = self.app.test_client()
        output = StringIO()
        with redirect_stdout(output):
            client.get("/")
            self.register(client, "camille")
            self.write(client, "/account/share")
            client.get("/reglages")
            self.write(client, "/activity/page", {"path": "/notes"})
            note = self.write(client, "/notes", NOTE).json["id"]
            self.write(client, f"/notes/{note}", NOTE, method="PUT")
            self.write(client, "/reminders", {})
            self.write(client, "/account/logout")
            self.write(client, "/account/login", {"username": "camille", "password": PASSWORD})
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 9)
        self.assertRegex(lines[0], r"^- \d{2}:\d{2}:\d{2} Chargement de page · Connexion$")
        for line in lines[1:]:
            self.assertRegex(line, r"^1 \d{2}:\d{2}:\d{2} ")
            self.assertNotIn(PASSWORD, line)
            self.assertNotIn(NOTE["title"], line)
        self.assertTrue(lines[4].endswith("Chargement de page · Notes"))
        self.assertTrue(lines[5].endswith("Création · note"))
        self.assertTrue(lines[6].endswith(f"Modification · note #{note}"))
        self.assertTrue(lines[-1].endswith("Connexion"))

    def test_legacy_records_can_be_assigned_by_the_server_operator(self):
        with transaction(self.database, write=True) as connection:
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            for number, migration in enumerate(MIGRATIONS[:7], start=1):
                for statement in migration:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {number}")
            connection.execute(
                """INSERT INTO notes(title, content, people, location, color, created_at, updated_at)
                   VALUES ('Ancienne note', 'Texte', '', '', '#aa3355', '2026-11-01', '2026-11-01')""",
            )
        initialize(self.database)
        first, owner = self.app.test_client(), self.app.test_client()
        self.assertEqual(self.register(first, "premier").status_code, 204)
        self.assertEqual(self.register(owner, "proprietaire").status_code, 204)
        self.assertEqual(first.get("/api/notes").status_code, 403)
        self.assertEqual(owner.get("/api/notes").status_code, 403)
        claim_existing(self.database, "PROPRIETAIRE")
        self.assertEqual(self.write(owner, "/account/share").status_code, 204)
        self.assertEqual(self.write(first, "/account/share").status_code, 204)
        self.assertEqual(owner.get("/api/notes").json[0]["title"], "Ancienne note")
        self.assertEqual(first.get("/api/notes").json, [])
