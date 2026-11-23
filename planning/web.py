import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from flask import Flask, g, jsonify, make_response, redirect, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .accounts import (
    AccountChanged, account_context, account_info, account_routes, account_transaction,
    current_account, find_account, has_session, login_digest,
)
from .activity import PAGES, log_activity
from .config import SITE_NAME
from .course_storage import CourseStorageError
from .database import transaction
from .library import PHOTO_REQUEST_LIMIT, library_routes
from .maintenance import maintenance_routes
from .organizer import move_to_trash, organizer_routes
from .rules import (
    CustodyCalendar, InputError, Period, boolean_value, calendar_range, civil_day,
    color_value, dates_between, event_fields, now_iso, parent_value,
    refresh_reminder_times, settings_fields, settings_row, text_value, timezone_for, timezone_value,
)
from .visits import record_visit, set_device_cookie


def json_input():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise InputError("Envoyez un objet JSON valide.")
    return data


def check_found(cursor, label):
    if cursor.rowcount == 0:
        raise InputError(f"{label} introuvable.", 404)


def day_note(row):
    item = dict(row)
    if item["checked"] is not None:
        item["checked"] = bool(item["checked"])
    return item


def day_note_fields(data):
    value = data.get("checked")
    if value is not None and type(value) is not bool:
        raise InputError("Indiquez si la case est cochée.")
    return (
        civil_day(data.get("day")).isoformat(),
        text_value(data, "author", "Auteur", length=80, required=True),
        text_value(data, "content", "Note", length=16000, required=True, multiline=True),
        value,
    )


def note_fields(data):
    day = civil_day(data["day"]).isoformat() if data.get("day") not in (None, "") else None
    return (
        text_value(data, "title", "Titre", length=120, required=True),
        text_value(data, "content", "Contenu", length=16000, required=True, multiline=True),
        day,
        text_value(data, "people", "Personnes", length=200),
        text_value(data, "location", "Lieu", length=200),
        color_value(data, "color"),
    )


def create_app(database, mode):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

    app.register_blueprint(account_routes(database, json_input))
    app.register_blueprint(organizer_routes(database))
    app.register_blueprint(library_routes(database, json_input, check_found))
    app.register_blueprint(maintenance_routes(database, mode, json_input))

    @app.before_request
    def same_origin_api():
        if request.endpoint == "library.complete_task":
            request.max_content_length = PHOTO_REQUEST_LIMIT
        if request.path.startswith("/api/"):
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                raise InputError("Ouvrez Planneli directement dans votre navigateur.", 403)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                if request.headers.get("X-Tempo-Request") != "1":
                    raise InputError("Requête Planneli attendue.", 403)
            if request.endpoint in {"accounts.register", "accounts.login"}:
                return
            g.account = current_account(database)
            if g.account is None:
                raise AccountChanged("Connectez-vous à votre compte Planneli.", 401)
            expected = request.headers.get("X-Tempo-Account")
            if expected is not None and expected != account_context(g.account):
                raise AccountChanged("Votre compte ou votre session a changé.", 409)
            if request.blueprint != "accounts" and request.endpoint != "session" and not has_session(g.account):
                raise AccountChanged("Créez ou rejoignez une session pour accéder à Planneli.", 403)
            g.workspace = g.account["workspace_id"]

    @app.after_request
    def response_headers(response):
        log_activity(response)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(InputError)
    def input_error(error):
        return {"error": str(error)}, error.status

    @app.errorhandler(AccountChanged)
    def account_changed(error):
        return {"error": str(error), "refresh": True}, error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            message = "Le fichier ou le formulaire est trop volumineux." if error.code == 413 else "Requête indisponible."
            return {"error": message}, error.code
        return error

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        if getattr(error, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return {"error": "La base est occupée. Réessayez dans un instant."}, 503
        app.logger.error("Erreur SQLite", exc_info=error)
        return {"error": "Une erreur de stockage est survenue."}, 500

    @app.errorhandler(CourseStorageError)
    def course_storage_error(error):
        app.logger.error("Erreur de stockage des cours", exc_info=error)
        return {"error": str(error)}, 503

    @app.get("/")
    @app.get("/planning")
    @app.get("/evenements")
    @app.get("/notes")
    @app.get("/reglages")
    @app.get("/a-faire")
    @app.get("/cours")
    @app.get("/jeux")
    def index():
        track_visit = request.method == "GET" and "prefetch" not in request.headers.get("Sec-Purpose", "")
        device, welcome = None, False
        with transaction(database, write=track_visit) as connection:
            g.account = account = find_account(connection, login_digest())
            if track_visit:
                device, welcome = record_visit(connection, account["id"] if account else None)
        active = account is not None and has_session(account)
        site_name = (account["site_name"] if account else "") or SITE_NAME
        page = PAGES[request.path] if active else "Choix de session" if account else "Connexion"
        g.activity_action = f"Chargement de page · {page}"
        response = make_response(render_template(
            "index.html", mode=mode, welcome=welcome, account=account_context(account) if account else None,
            active=active, site_name=site_name, default_site_name=SITE_NAME,
        ))
        response.headers["Cache-Control"] = "no-store"
        set_device_cookie(response, device)
        return response

    @app.get("/applications")
    def former_applications():
        return redirect("/jeux")

    @app.get("/service-worker.js")
    def service_worker():
        return send_from_directory(app.static_folder, "service-worker.js", max_age=0)

    @app.get("/api/session")
    def session():
        with account_transaction(database) as connection:
            if not has_session(g.account):
                return {"account": account_info(g.account), "settings": None}
            settings = settings_row(connection, g.workspace)
            zone = timezone_for(connection, g.workspace, settings)
        today = datetime.now(zone).date()
        return {
            "account": account_info(g.account), "settings": dict(settings) if settings else None,
            "today": today.isoformat(), "timezone": zone.key,
        }

    @app.post("/api/activity/page")
    def page_activity():
        path = json_input().get("path")
        if not isinstance(path, str) or path not in PAGES:
            raise InputError("Page inconnue.", 404)
        g.activity_action = f"Chargement de page · {PAGES[path]}"
        return "", 204

    @app.post("/api/settings")
    def create_settings():
        data = json_input()
        first = civil_day(data.get("anchor"), "Semaine de référence")
        monday = first - timedelta(days=first.weekday())
        parent = parent_value(data.get("first_parent"))
        fields = settings_fields(data)
        with account_transaction(database, write=True) as connection:
            if settings_row(connection, g.workspace) is not None:
                raise InputError("Les parents sont déjà configurés.", 409)
            connection.execute(
                """INSERT INTO settings(workspace_id, name_a, color_a, name_b, color_b, timezone, anchor, first_parent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (g.workspace, *fields, monday.isoformat(), parent),
            )
            refresh_reminder_times(connection, g.workspace, timezone_value(fields[-1]))
        return "", 204

    @app.put("/api/settings")
    def update_settings():
        fields = settings_fields(json_input())
        with account_transaction(database, write=True) as connection:
            previous = settings_row(connection, g.workspace, required=True)
            connection.execute(
                "UPDATE settings SET name_a = ?, color_a = ?, name_b = ?, color_b = ?, timezone = ? WHERE workspace_id = ?",
                (*fields, g.workspace),
            )
            if previous["timezone"] != fields[-1]:
                refresh_reminder_times(connection, g.workspace, timezone_value(fields[-1]))
        return "", 204

    @app.get("/api/planning")
    def planning():
        first, last = calendar_range(request.args)
        with account_transaction(database) as connection:
            calendar = CustodyCalendar(connection, g.workspace, first, last)
            carers = defaultdict(list)
            for row in connection.execute(
                """SELECT weekday, name FROM carer_days JOIN carers ON carers.id = carer_id
                   WHERE carers.workspace_id = ? AND active = 1 ORDER BY name COLLATE NOCASE, carers.id""",
                (g.workspace,),
            ):
                carers[row["weekday"]].append(row["name"])
            counts = dict(connection.execute(
                "SELECT day, COUNT(*) FROM day_notes WHERE workspace_id = ? AND day BETWEEN ? AND ? GROUP BY day",
                (g.workspace, first.isoformat(), last.isoformat()),
            ))
        return {
            day.isoformat(): {
                "parent": calendar.parent(day),
                "custom": day.isoformat() in calendar.overrides,
                "carers": carers.get(day.weekday(), []),
                "note_count": counts.get(day.isoformat(), 0),
            }
            for day in dates_between(first, last)
        }

    @app.get("/api/weekends")
    def list_weekends():
        with account_transaction(database) as connection:
            rows = connection.execute(
                "SELECT year FROM weekend_switches WHERE workspace_id = ? ORDER BY year", (g.workspace,),
            ).fetchall()
        return jsonify([row["year"] for row in rows])

    @app.put("/api/weekends/<int:year>")
    def update_weekend(year):
        if not 1 <= year <= 9999:
            raise InputError("Choisissez une année valide.")
        enabled = boolean_value(json_input(), "enabled", "Inversion des week-ends")
        with account_transaction(database, write=True) as connection:
            settings_row(connection, g.workspace, required=True)
            if enabled:
                connection.execute("INSERT OR IGNORE INTO weekend_switches VALUES (?, ?)", (g.workspace, year))
            else:
                connection.execute("DELETE FROM weekend_switches WHERE workspace_id = ? AND year = ?", (g.workspace, year))
        return "", 204

    @app.post("/api/assignments/preview")
    def preview_assignment():
        period = Period.from_json(json_input())
        with account_transaction(database) as connection:
            calendar = CustodyCalendar(connection, g.workspace, period.first, period.last)
        return period.preview(calendar)

    @app.post("/api/assignments")
    def apply_assignment():
        data = json_input()
        period = Period.from_json(data)
        with account_transaction(database, write=True) as connection:
            calendar = CustodyCalendar(connection, g.workspace, period.first, period.last)
            if period.preview(calendar)["token"] != data.get("token"):
                raise InputError("Recalculez l’aperçu. Le planning ou la période a changé.", 409)
            period.apply(connection, calendar)
        return "", 204

    @app.get("/api/carers")
    def list_carers():
        carers = {}
        with account_transaction(database) as connection:
            for row in connection.execute(
                """SELECT carers.id, name, active, weekday FROM carers
                   JOIN carer_days ON carer_id = carers.id
                   WHERE carers.workspace_id = ? ORDER BY name COLLATE NOCASE, carers.id, weekday""", (g.workspace,),
            ):
                carer = carers.setdefault(row["id"], {
                    "id": row["id"], "name": row["name"], "active": bool(row["active"]), "days": [],
                })
                carer["days"].append(row["weekday"])
        return jsonify(list(carers.values()))

    @app.post("/api/carers")
    @app.put("/api/carers/<int:carer_id>")
    def save_carer(carer_id=None):
        data = json_input()
        name = text_value(data, "name", "Nom", length=80, required=True)
        active = boolean_value(data, "active", "Garde active")
        days = data.get("days")
        if not isinstance(days, list) or not days or any(type(day) is not int or not 0 <= day <= 6 for day in days):
            raise InputError("Sélectionnez au moins un jour de la semaine.")
        with account_transaction(database, write=True) as connection:
            settings_row(connection, g.workspace, required=True)
            if carer_id is None:
                carer_id = connection.execute(
                    "INSERT INTO carers(name, active, workspace_id) VALUES (?, ?, ?)", (name, active, g.workspace)
                ).lastrowid
            else:
                cursor = connection.execute(
                    "UPDATE carers SET name = ?, active = ? WHERE id = ? AND workspace_id = ?",
                    (name, active, carer_id, g.workspace),
                )
                check_found(cursor, "Personne de garde")
                connection.execute("DELETE FROM carer_days WHERE carer_id = ?", (carer_id,))
            connection.executemany(
                "INSERT INTO carer_days(carer_id, weekday) VALUES (?, ?)",
                [(carer_id, day) for day in set(days)],
            )
        return {"id": carer_id}

    @app.delete("/api/carers/<int:carer_id>")
    def delete_carer(carer_id):
        with account_transaction(database, write=True) as connection:
            check_found(connection.execute(
                "DELETE FROM carers WHERE id = ? AND workspace_id = ?", (carer_id, g.workspace),
            ), "Personne de garde")
        return "", 204

    @app.get("/api/day-notes")
    def list_day_notes():
        day = civil_day(request.args.get("day")).isoformat()
        with account_transaction(database) as connection:
            rows = connection.execute(
                "SELECT * FROM day_notes WHERE workspace_id = ? AND day = ? ORDER BY id", (g.workspace, day),
            ).fetchall()
        return jsonify([day_note(row) for row in rows])

    @app.post("/api/day-notes")
    def create_day_note():
        fields = day_note_fields(json_input())
        with account_transaction(database, write=True) as connection:
            settings_row(connection, g.workspace, required=True)
            note_id = connection.execute(
                "INSERT INTO day_notes(day, author, content, checked, workspace_id) VALUES (?, ?, ?, ?, ?)",
                (*fields, g.workspace),
            ).lastrowid
        return {"id": note_id}, 201

    @app.put("/api/day-notes/<int:note_id>")
    def update_day_note(note_id):
        fields = day_note_fields(json_input())
        with account_transaction(database, write=True) as connection:
            cursor = connection.execute(
                "UPDATE day_notes SET day = ?, author = ?, content = ?, checked = ? WHERE id = ? AND workspace_id = ?",
                (*fields, note_id, g.workspace),
            )
            check_found(cursor, "Note")
        return "", 204

    @app.patch("/api/day-notes/<int:note_id>")
    def toggle_day_note(note_id):
        checked = boolean_value(json_input(), "checked", "Case à cocher")
        with account_transaction(database, write=True) as connection:
            cursor = connection.execute(
                "UPDATE day_notes SET checked = ? WHERE id = ? AND workspace_id = ? AND checked IS NOT NULL",
                (checked, note_id, g.workspace),
            )
            check_found(cursor, "Case à cocher")
        return "", 204

    @app.delete("/api/day-notes/<int:note_id>")
    def delete_day_note(note_id):
        with account_transaction(database, write=True) as connection:
            check_found(connection.execute(
                "DELETE FROM day_notes WHERE id = ? AND workspace_id = ?", (note_id, g.workspace),
            ), "Note")
        return "", 204

    @app.get("/api/events")
    def list_events():
        first, last = calendar_range(request.args)
        with account_transaction(database) as connection:
            rows = connection.execute(
                """SELECT * FROM events WHERE workspace_id = ? AND deleted_at IS NULL AND day BETWEEN ? AND ?
                   ORDER BY day, start_time, id""",
                (g.workspace, first.isoformat(), last.isoformat()),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/events/<int:event_id>")
    def get_event(event_id):
        with account_transaction(database) as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL", (event_id, g.workspace),
            ).fetchone()
        if row is None:
            raise InputError("Événement introuvable.", 404)
        return dict(row)

    @app.post("/api/events")
    @app.put("/api/events/<int:event_id>")
    def save_event(event_id=None):
        data = json_input()
        with account_transaction(database, write=True) as connection:
            settings = settings_row(connection, g.workspace)
            fields = event_fields(data, timezone_for(connection, g.workspace, settings))
            if event_id is None:
                event_id = connection.execute(
                    """INSERT INTO events(title, day, start_time, end_time, location, note, color,
                                          reminder_minutes, remind_at, workspace_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*fields, g.workspace),
                ).lastrowid
                return {"id": event_id}, 201
            cursor = connection.execute(
                """UPDATE events SET title = ?, day = ?, start_time = ?, end_time = ?, location = ?,
                   note = ?, color = ?, reminder_minutes = ?, remind_at = ?
                   WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL""",
                (*fields, event_id, g.workspace),
            )
            check_found(cursor, "Événement")
        return {"id": event_id}

    @app.delete("/api/events/<int:event_id>")
    def delete_event(event_id):
        with account_transaction(database, write=True) as connection:
            check_found(move_to_trash(connection, "events", event_id), "Événement")
        return "", 204

    @app.post("/api/reminders")
    def reminders():
        raw = json_input().get("client")
        try:
            client = str(UUID(raw, version=4))
            if raw != client:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise InputError("Identifiant de navigateur invalide.") from None
        now = int(time.time())
        with account_transaction(database, write=True) as connection:
            rows = connection.execute(
                """SELECT id, title, day, start_time, remind_at FROM events
                   WHERE workspace_id = ? AND deleted_at IS NULL AND remind_at BETWEEN ? AND ? AND NOT EXISTS (
                     SELECT 1 FROM reminder_receipts
                     WHERE client = ? AND event_id = events.id AND remind_at = events.remind_at
                   ) ORDER BY remind_at, id""",
                (g.workspace, now - 3600, now, client),
            ).fetchall()
            connection.executemany(
                "INSERT INTO reminder_receipts(client, event_id, remind_at) VALUES (?, ?, ?)",
                [(client, row["id"], row["remind_at"]) for row in rows],
            )
        return jsonify([dict(row) for row in rows])

    @app.get("/api/notes")
    def list_notes():
        with account_transaction(database) as connection:
            rows = connection.execute(
                "SELECT * FROM notes WHERE workspace_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC, id DESC",
                (g.workspace,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/notes")
    @app.put("/api/notes/<int:note_id>")
    def save_note(note_id=None):
        fields = note_fields(json_input())
        stamp = now_iso()
        with account_transaction(database, write=True) as connection:
            if note_id is None:
                note_id = connection.execute(
                    """INSERT INTO notes(title, content, day, people, location, color, created_at, updated_at, workspace_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*fields, stamp, stamp, g.workspace),
                ).lastrowid
                return {"id": note_id}, 201
            cursor = connection.execute(
                """UPDATE notes SET title = ?, content = ?, day = ?, people = ?,
                   location = ?, color = ?, updated_at = ? WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL""",
                (*fields, stamp, note_id, g.workspace),
            )
            check_found(cursor, "Note")
        return {"id": note_id}

    @app.delete("/api/notes/<int:note_id>")
    def delete_note(note_id):
        with account_transaction(database, write=True) as connection:
            check_found(move_to_trash(connection, "notes", note_id), "Note")
        return "", 204

    return app
