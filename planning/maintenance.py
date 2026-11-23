import hashlib
import os
import secrets
import time
from collections import deque
from functools import wraps
from threading import Lock

from flask import Blueprint, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer

from .config import PROJECT
from .database import transaction
from .rules import InputError, now_iso
from .updates import REPOSITORY, fetch_release, pending_revision


DEVICE_COOKIE = "naoning_device"
ACCESS_COOKIE = "naoning_maintenance"
ACCESS_SECONDS = 900
RAW_TABLES = (
    "settings", "day_overrides", "weekend_switches", "carers", "carer_days",
    "day_notes", "events", "notes", "tasks", "subjects", "courses",
)
RESET_TABLES = {
    "planning": ("day_overrides", "weekend_switches", "carers", "day_notes", "settings"),
    "notes": ("notes",),
    "events": ("events",),
}


def log_connection(database):
    if request.method != "GET" or "prefetch" in request.headers.get("Sec-Purpose", ""):
        return None, False
    device = request.cookies.get(DEVICE_COOKIE, "")
    issued = None
    if len(device) != 43 or not all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in device):
        device = issued = secrets.token_urlsafe(32)
    digest = hashlib.sha256(device.encode("ascii")).hexdigest()
    ip = request.remote_addr or "inconnue"
    with transaction(database, write=True) as connection:
        visitor = connection.execute(
            "SELECT id FROM visitors WHERE ip = ? AND device = ?", (ip, digest)
        ).fetchone()
        first = visitor is None
        visitor_id = connection.execute(
            "INSERT INTO visitors(ip, device) VALUES (?, ?)", (ip, digest)
        ).lastrowid if first else visitor["id"]
        connection.execute(
            "INSERT INTO connections(visitor_id, connected_at) VALUES (?, ?)", (visitor_id, now_iso())
        )
    return issued, first


def maintenance_routes(database, mode, json_input):
    blueprint = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")
    signer = URLSafeTimedSerializer(secrets.token_urlsafe(32), salt=ACCESS_COOKIE)
    pin = os.environ.get("NAONING_MAINTENANCE_CODE", "20072009").encode("utf-8")
    attempts = {}
    attempt_lock = Lock()
    update_lock = Lock()

    def authorized(handler):
        @wraps(handler)
        def wrapped(*args, **kwargs):
            try:
                identity = signer.loads(request.cookies.get(ACCESS_COOKIE, ""), max_age=ACCESS_SECONDS)
            except BadData:
                raise InputError("Saisissez le code de maintenance pour continuer.", 401) from None
            if identity != [request.remote_addr, request.cookies.get(DEVICE_COOKIE)]:
                raise InputError("Saisissez le code de maintenance pour continuer.", 401)
            return handler(*args, **kwargs)
        return wrapped

    @blueprint.post("/unlock")
    def unlock():
        code = json_input().get("code")
        ip = request.remote_addr
        with attempt_lock:
            cutoff = time.monotonic() - ACCESS_SECONDS
            for address, history in list(attempts.items()):
                while history and history[0] <= cutoff:
                    history.popleft()
                if not history:
                    del attempts[address]
            history = attempts.setdefault(ip, deque())
            if len(history) >= 5:
                raise InputError("Trop de tentatives. Réessayez dans quelques minutes.", 429)
            if not isinstance(code, str) or not secrets.compare_digest(code.encode("utf-8", "replace"), pin):
                history.append(time.monotonic())
                raise InputError("Code incorrect.", 403)
            attempts.pop(ip, None)
        response = jsonify({"authorized": True})
        response.set_cookie(
            ACCESS_COOKIE, signer.dumps([ip, request.cookies.get(DEVICE_COOKIE)]),
            max_age=ACCESS_SECONDS, httponly=True, samesite="Strict", secure=request.is_secure,
        )
        return response

    @blueprint.post("/lock")
    def lock():
        response = jsonify({"authorized": False})
        response.delete_cookie(ACCESS_COOKIE, httponly=True, samesite="Strict", secure=request.is_secure)
        return response

    @blueprint.get("")
    @authorized
    def overview():
        with transaction(database) as connection:
            logs = connection.execute(
                """SELECT connections.id, visitor_id, ip, connected_at
                   FROM connections JOIN visitors ON visitors.id = visitor_id
                   ORDER BY connections.id DESC LIMIT 100"""
            ).fetchall()
            visitors = connection.execute(
                """SELECT visitors.id, visitors.ip, latest.connected_at AS last_connected_at
                   FROM visitors JOIN connections AS latest ON latest.id = (
                       SELECT id FROM connections WHERE visitor_id = visitors.id ORDER BY id DESC LIMIT 1
                   ) ORDER BY latest.id DESC"""
            ).fetchall()
        return {
            "logs": [dict(row) for row in logs],
            "visitors": [dict(row) for row in visitors],
            "repository": REPOSITORY,
            "pending": pending_revision(PROJECT),
            "can_update": mode == "normal",
        }

    @blueprint.delete("/visitors/<int:visitor_id>")
    @authorized
    def delete_visitor(visitor_id):
        if not 0 < visitor_id <= 2**63 - 1:
            raise InputError("Identifiant introuvable.", 404)
        with transaction(database, write=True) as connection:
            connection.execute("DELETE FROM connections WHERE visitor_id = ?", (visitor_id,))
            deleted = connection.execute("DELETE FROM visitors WHERE id = ?", (visitor_id,))
            if deleted.rowcount == 0:
                raise InputError("Identifiant introuvable.", 404)
        return "", 204

    @blueprint.delete("/data/<scope>")
    @authorized
    def clear_data(scope):
        tables = RESET_TABLES.get(scope)
        if tables is None:
            raise InputError("Catégorie introuvable.", 404)
        with transaction(database, write=True) as connection:
            if scope == "planning":
                connection.execute(
                    """INSERT INTO app_preferences(key, value)
                       SELECT 'timezone', timezone FROM settings WHERE id = 1
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value"""
                )
            for table in tables:
                connection.execute(f"DELETE FROM {table}")
        return "", 204

    @blueprint.get("/data")
    @authorized
    def data():
        with transaction(database) as connection:
            data = {
                table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
                for table in RAW_TABLES
            }
            data["task_photos"] = [dict(row) for row in connection.execute(
                "SELECT id, task_id, filename, mime FROM task_photos ORDER BY id"
            )]
            return data

    @blueprint.post("/update")
    @authorized
    def update():
        if mode != "normal":
            raise InputError("Passez en mode normal pour préparer une mise à jour.", 409)
        if not update_lock.acquire(blocking=False):
            raise InputError("Une vérification est déjà en cours.", 409)
        try:
            return {"revision": fetch_release(PROJECT)}
        except (ValueError, OSError) as error:
            raise InputError(str(error), 409) from error
        finally:
            update_lock.release()

    return blueprint
