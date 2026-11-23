import os
import secrets
import time
from collections import deque
from functools import wraps
from threading import Lock

from flask import Blueprint, g, jsonify, make_response, request
from itsdangerous import BadData, URLSafeTimedSerializer

from .accounts import MAINTENANCE_COOKIE as ACCESS_COOKIE, account_transaction, clear_login
from .config import PROJECT
from .database import WORKSPACE_TABLES
from .rules import InputError
from .updates import REPOSITORY, fetch_release, pending_revision
from .visits import DEVICE_COOKIE


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


def find_maintenance_account(connection, account_id):
    account = connection.execute(
        """SELECT accounts.id, username, (share_code IS NOT NULL) AS hosts_session
           FROM accounts JOIN workspaces ON workspaces.id = own_workspace WHERE accounts.id = ?""",
        (account_id,),
    ).fetchone()
    if account is None:
        raise InputError("Compte introuvable.", 404)
    return account


def maintenance_routes(database, mode, json_input):
    blueprint = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")
    signer = URLSafeTimedSerializer(secrets.token_urlsafe(32), salt=ACCESS_COOKIE)
    code = os.environ.get("NAONING_MAINTENANCE_CODE")
    if not code:
        code = f"{secrets.randbelow(10**8):08d}"
        print(f"Code de maintenance · {code}", flush=True)
    pin = code.encode("utf-8")
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
            if identity != [request.remote_addr, request.cookies.get(DEVICE_COOKIE), g.account["id"]]:
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
            ACCESS_COOKIE, signer.dumps([ip, request.cookies.get(DEVICE_COOKIE), g.account["id"]]),
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
        with account_transaction(database) as connection:
            logs = connection.execute(
                """SELECT connections.id, visitor_id, visitors.account_id, accounts.username, ip, connected_at
                   FROM connections JOIN visitors ON visitors.id = visitor_id
                   LEFT JOIN accounts ON accounts.id = visitors.account_id
                   ORDER BY connections.id DESC LIMIT 100"""
            ).fetchall()
            accounts = connection.execute(
                """SELECT accounts.id, username, COUNT(visitors.id) AS visitor_count
                   FROM accounts LEFT JOIN visitors ON visitors.account_id = accounts.id
                   GROUP BY accounts.id ORDER BY username_key"""
            ).fetchall()
        return {
            "logs": [dict(row) for row in logs],
            "accounts": [dict(row) for row in accounts],
            "repository": REPOSITORY,
            "pending": pending_revision(PROJECT),
            "can_update": mode == "normal",
        }

    @blueprint.get("/accounts/<int:account_id>")
    @authorized
    def account_details(account_id):
        if not 0 < account_id <= 2**63 - 1:
            raise InputError("Compte introuvable.", 404)
        with account_transaction(database) as connection:
            account = find_maintenance_account(connection, account_id)
            visitors = connection.execute(
                """SELECT visitors.id, visitors.ip, latest.connected_at AS last_connected_at
                   FROM visitors JOIN connections AS latest ON latest.id = (
                       SELECT id FROM connections WHERE visitor_id = visitors.id ORDER BY id DESC LIMIT 1
                   ) WHERE visitors.account_id = ? ORDER BY latest.id DESC""", (account_id,),
            ).fetchall()
        return {
            **dict(account), "visitors": [dict(row) for row in visitors], "is_current": account_id == g.account["id"],
        }

    @blueprint.delete("/visitors/<int:visitor_id>")
    @blueprint.delete("/accounts/<int:account_id>/visitors/<int:visitor_id>")
    @authorized
    def delete_visitor(visitor_id, account_id=None):
        if not 0 < visitor_id <= 2**63 - 1 or (account_id is not None and not 0 < account_id <= 2**63 - 1):
            raise InputError("Identifiant introuvable.", 404)
        with account_transaction(database, write=True) as connection:
            visitor = connection.execute(
                "SELECT id FROM visitors WHERE id = ? AND (? IS NULL OR account_id = ?)",
                (visitor_id, account_id, account_id),
            ).fetchone()
            if visitor is None:
                raise InputError("Identifiant introuvable.", 404)
            connection.execute("DELETE FROM connections WHERE visitor_id = ?", (visitor_id,))
            connection.execute("DELETE FROM visitors WHERE id = ?", (visitor_id,))
        return "", 204

    @blueprint.delete("/accounts/<int:account_id>")
    @authorized
    def delete_account(account_id):
        if not 0 < account_id <= 2**63 - 1:
            raise InputError("Compte introuvable.", 404)
        with account_transaction(database, write=True) as connection:
            find_maintenance_account(connection, account_id)
            connection.execute(
                "DELETE FROM connections WHERE visitor_id IN (SELECT id FROM visitors WHERE account_id = ?)",
                (account_id,),
            )
            connection.execute("DELETE FROM visitors WHERE account_id = ?", (account_id,))
            connection.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if account_id == g.account["id"]:
            return clear_login(make_response("", 204))
        return "", 204

    @blueprint.delete("/data/<scope>")
    @authorized
    def clear_data(scope):
        tables = RESET_TABLES.get(scope)
        if tables is None:
            raise InputError("Catégorie introuvable.", 404)
        with account_transaction(database, write=True) as connection:
            if scope == "planning":
                connection.execute(
                    """INSERT INTO app_preferences(workspace_id, key, value)
                       SELECT workspace_id, 'timezone', timezone FROM settings WHERE workspace_id = ?
                       ON CONFLICT(workspace_id, key) DO UPDATE SET value = excluded.value""", (g.workspace,),
                )
            for table in tables:
                connection.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (g.workspace,))
        return "", 204

    @blueprint.get("/data")
    @authorized
    def data():
        with account_transaction(database) as connection:
            data = {}
            for table in RAW_TABLES:
                if table in WORKSPACE_TABLES:
                    rows = connection.execute(f"SELECT * FROM {table} WHERE workspace_id = ?", (g.workspace,))
                elif table == "carer_days":
                    rows = connection.execute(
                        "SELECT carer_days.* FROM carer_days JOIN carers ON carer_id = carers.id WHERE workspace_id = ?",
                        (g.workspace,),
                    )
                else:
                    rows = connection.execute(f"SELECT * FROM {table}")
                data[table] = [dict(row) for row in rows]
            data["task_photos"] = [dict(row) for row in connection.execute(
                """SELECT task_photos.id, task_id, filename, mime FROM task_photos
                   JOIN tasks ON task_id = tasks.id WHERE workspace_id = ? ORDER BY task_photos.id""", (g.workspace,),
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
