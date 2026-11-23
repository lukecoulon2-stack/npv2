import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from planning.accounts import LOGIN_COOKIE
from planning.config import PROJECT, read_config
from planning.database import APPLICATION_ID, MIGRATIONS, backup, initialize, restore, transaction
from planning.web import create_app


WRITE_HEADERS = {"X-Tempo-Request": "1"}
PARENTS = {
    "name_a": "Anaëlle", "color_a": "#8f5cd8",
    "name_b": "Bastien", "color_b": "#358eaf",
    "anchor": "2026-12-30", "first_parent": 1, "timezone": "Europe/Paris",
}


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.work = TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.path = Path(self.work.name) / "planning.sqlite3"
        initialize(self.path)
        self.app = create_app(self.path, "bench")
        self.client = self.app.test_client()
        self.assertEqual(self.write("POST", "/account/register", {
            "username": "parents", "password": "un-mot-de-passe-de-test",
        }).status_code, 204)
        self.assertEqual(self.write("POST", "/account/share").status_code, 204)
        self.assertEqual(self.write("POST", "/settings", PARENTS).status_code, 204)

    def write(self, method, route, data=None):
        return self.client.open("/api" + route, method=method, json=data, headers=WRITE_HEADERS)

    def read(self, route):
        response = self.client.get("/api" + route)
        self.assertEqual(response.status_code, 200)
        return response.json

    def parent_on(self, day):
        return self.read(f"/planning?start={day}&end={day}")[day]["parent"]

    def apply_period(self, period):
        preview = self.write("POST", "/assignments/preview", period)
        self.assertEqual(preview.status_code, 200)
        applied = self.write("POST", "/assignments", {**period, "token": preview.json["token"]})
        self.assertEqual(applied.status_code, 204)

    def test_alternance_traverse_annee_et_weekends_civils(self):
        self.assertEqual(self.read("/session")["settings"]["anchor"], "2026-12-28")
        self.assertEqual(self.parent_on("2026-12-26"), 2)
        self.assertEqual(self.parent_on("2026-12-31"), 1)
        self.assertEqual(self.parent_on("2027-01-02"), 1)
        self.assertEqual(self.parent_on("2027-01-04"), 2)
        self.assertEqual(self.write("PUT", "/weekends/2026", {"enabled": True}).status_code, 204)
        self.assertEqual(self.parent_on("2026-12-26"), 1)
        self.assertEqual(self.parent_on("2026-12-27"), 1)
        self.assertEqual(self.parent_on("2027-01-02"), 1)
        self.assertEqual(self.write("PUT", "/weekends/2026", {"enabled": False}).status_code, 204)
        self.assertEqual(self.parent_on("2026-12-27"), 2)

    def test_exception_prioritaire_et_apercu_recalcule(self):
        self.apply_period({"start": "2026-12-27", "end": "2026-12-27", "action": "assign", "parent": 2})
        period = {"start": "2026-12-26", "end": "2026-12-28", "action": "invert"}
        preview = self.write("POST", "/assignments/preview", period).json
        self.write("PUT", "/weekends/2026", {"enabled": True})
        self.assertEqual(self.parent_on("2026-12-27"), 2)
        refused = self.write("POST", "/assignments", {**period, "token": preview["token"]})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.parent_on("2026-12-28"), 1)
        self.apply_period(period)
        self.assertEqual(
            [self.parent_on(f"2026-12-{day}") for day in (26, 27, 28)],
            [2, 1, 2],
        )
        self.apply_period({**period, "action": "clear"})
        self.assertEqual(
            [self.parent_on(f"2026-12-{day}") for day in (26, 27, 28)],
            [1, 1, 1],
        )

    def test_garde_suspendue_et_case_persistante(self):
        carer = {"name": "Camille", "days": [4, 5], "active": True}
        identifier = self.write("POST", "/carers", carer).json["id"]
        day = "2026-12-25"
        route = f"/planning?start={day}&end={day}"
        self.assertEqual(self.read(route)[day]["carers"], ["Camille"])
        note = {"day": day, "author": "Anaëlle", "content": "Écharpe\nGoûter", "checked": False}
        note_id = self.write("POST", "/day-notes", note).json["id"]
        self.assertEqual(self.write("PATCH", f"/day-notes/{note_id}", {"checked": True}).status_code, 204)
        self.write("PUT", f"/carers/{identifier}", {**carer, "active": False})
        initialize(self.path)
        self.assertEqual(self.read(route)[day]["carers"], [])
        self.assertEqual(self.read(route)[day]["note_count"], 1)
        saved = self.read(f"/day-notes?day={day}")[0]
        self.assertTrue(saved["checked"])
        self.assertEqual(saved["content"], "Écharpe\nGoûter")

    def test_rappel_recalcule_selon_le_fuseau_et_deduplique(self):
        event = {
            "title": "Rendez-vous", "day": "2026-03-29", "start_time": "10:00",
            "end_time": "11:00", "color": "#5577ca", "reminder_minutes": 30,
        }
        identifier = self.write("POST", "/events", event).json["id"]
        paris = int(datetime(2026, 3, 29, 7, 30, tzinfo=timezone.utc).timestamp())
        montreal = int(datetime(2026, 3, 29, 13, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual(self.read(f"/events/{identifier}")["remind_at"], paris)
        self.assertEqual(self.write("PUT", "/settings", {**PARENTS, "timezone": "America/Montreal"}).status_code, 204)
        self.assertEqual(self.read(f"/events/{identifier}")["remind_at"], montreal)
        self.assertEqual(self.write("PUT", f"/events/{identifier}", {**event, "end_time": "09:59"}).status_code, 400)

        token = self.client.get_cookie(LOGIN_COOKIE).value

        def fetch(client_id):
            with self.app.test_client() as http:
                http.set_cookie(LOGIN_COOKIE, token)
                return http.post("/api/reminders", json={"client": client_id}, headers=WRITE_HEADERS).json

        with patch("planning.web.time.time", return_value=montreal + 10):
            same_client = str(uuid4())
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(fetch, [same_client, same_client]))
            self.assertEqual(sum(map(len, results)), 1)
            self.assertEqual(len(fetch(str(uuid4()))), 1)
            self.assertEqual(fetch(same_client), [])

    def test_notes_et_evenements_sans_heure(self):
        event = {
            "title": "Anniversaire", "day": "2026-12-25", "color": "#dc7741",
            "location": "À la maison", "note": "Prévoir le gâteau.", "reminder_minutes": 0,
        }
        identifier = self.write("POST", "/events", event).json["id"]
        saved = self.read(f"/events/{identifier}")
        self.assertIsNone(saved["start_time"])
        self.assertEqual(saved["remind_at"], datetime(2026, 12, 25, 8, tzinfo=timezone.utc).timestamp())
        note = {"title": "Mémo", "content": "Été\nHiver", "color": "#11bbee", "people": "Bastien"}
        result = self.write("POST", "/notes", note)
        self.assertEqual(result.status_code, 201)
        self.write("PUT", f"/notes/{result.json['id']}", {**note, "title": "Mémo modifié"})
        self.assertEqual(self.read("/notes")[0]["title"], "Mémo modifié")
        self.assertEqual(self.read("/notes")[0]["content"], "Été\nHiver")

    def test_les_ecritures_requierent_l_en_tete_de_l_application(self):
        self.assertEqual(self.client.post("/api/notes", json={}).status_code, 403)
        response = self.client.get("/api/notes", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.read("/notes"), [])


class StorageTests(unittest.TestCase):
    def test_migration_sauvegarde_et_restauration(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "current.sqlite3"
            snapshot = path.with_name("snapshot.sqlite3")
            with transaction(path, write=True) as connection:
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                for statement in MIGRATIONS[0]:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                connection.execute(
                    """INSERT INTO notes(title, content, people, location, color, created_at, updated_at)
                       VALUES ('Mémo', 'Été', '', '', '#bb3377', '2026-11-01', '2026-11-01')"""
                )
            initialize(path)
            with transaction(path) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS))
                self.assertEqual(connection.execute("SELECT content FROM notes").fetchone()[0], "Été")
            backup(path, snapshot)
            with self.assertRaises(FileExistsError):
                backup(path, snapshot)
            with transaction(path, write=True) as connection:
                connection.execute("UPDATE notes SET content = 'Hiver'")
            previous = restore(snapshot, path)
            self.assertTrue(previous.is_file())
            with transaction(path) as connection:
                self.assertEqual(connection.execute("SELECT content FROM notes").fetchone()[0], "Été")
            with transaction(previous) as connection:
                self.assertEqual(connection.execute("SELECT content FROM notes").fetchone()[0], "Hiver")
            wrong = path.with_name("other.sqlite3")
            with sqlite3.connect(wrong) as unrelated:
                unrelated.execute("CREATE TABLE unrelated(id INTEGER)")
            with self.assertRaisesRegex(ValueError, "compatible"):
                restore(wrong, path)

    def test_configuration_rejette_port_invalide_et_dossier_dans_le_projet(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            options = {"mode": "normal", "host": "127.0.0.1", "port": 8042, "data_dir": directory}
            path.write_text(json.dumps(options), encoding="utf-8")
            self.assertEqual(read_config(path).port, 8042)
            for key, value in (("port", True), ("port", 70000), ("data_dir", str(PROJECT))):
                path.write_text(json.dumps({**options, key: value}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, key):
                    read_config(path)
            path.write_text(json.dumps({**options, "mode": "bench", "data_dir": str(PROJECT)}), encoding="utf-8")
            self.assertIsNone(read_config(path).data_dir)


if __name__ == "__main__":
    unittest.main()
