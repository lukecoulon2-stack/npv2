import hashlib
import re
import secrets
import time
import unicodedata
from collections import deque
from contextlib import contextmanager
from threading import Lock

from flask import Blueprint, g, make_response, request
from werkzeug.security import check_password_hash, generate_password_hash

from .config import SITE_NAME
from .database import WORKSPACE_TABLES, transaction
from .rules import InputError, text_value
from .visits import record_visit, set_device_cookie


LOGIN_COOKIE = "naoning_account"
MAINTENANCE_COOKIE = "naoning_maintenance"
LOGIN_SECONDS = 30 * 86400
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
ATTEMPT_WINDOW = 15 * 60


class AccountChanged(InputError):
    pass


def username_key(username):
    return unicodedata.normalize("NFC", username.strip()).casefold()


def credentials(data):
    username = data.get("username")
    username = unicodedata.normalize("NFC", username.strip()) if isinstance(username, str) else ""
    if not 3 <= len(username) <= 40 or not all(ch.isalnum() or ch in "._-" for ch in username):
        raise InputError("Utilisez un nom de 3 à 40 caractères parmi les lettres, les chiffres et . _ -")
    password = data.get("password")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise InputError("Le mot de passe doit contenir entre 8 et 128 caractères.")
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        raise InputError("Le mot de passe contient un caractère invalide.") from None
    return username, password


def login_digest():
    token = request.cookies.get(LOGIN_COOKIE, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()
    return None


def find_account(connection, digest):
    return connection.execute(
        """SELECT accounts.id, accounts.username, accounts.own_workspace, accounts.joined_workspace, accounts.site_name,
                  workspaces.id AS workspace_id, workspaces.share_code, owners.username AS owner
           FROM account_logins JOIN accounts ON accounts.id = account_id
           JOIN workspaces ON workspaces.id = COALESCE(accounts.joined_workspace, accounts.own_workspace)
           LEFT JOIN accounts AS owners ON owners.own_workspace = workspaces.id
           WHERE token_hash = ? AND expires_at > ?""",
        (digest, int(time.time())),
    ).fetchone()


def current_account(database):
    digest = login_digest()
    if digest is not None:
        with transaction(database) as connection:
            return find_account(connection, digest)
    return None


def account_context(account):
    return f"{account['id']}:{account['workspace_id']}"


def has_session(account):
    return account["share_code"] is not None


@contextmanager
def account_transaction(database, *, write=False, course_files=False):
    with transaction(database, write=write, course_files=course_files) as connection:
        account = find_account(connection, login_digest())
        if account is None:
            raise AccountChanged("Connectez-vous à votre compte Planneli.", 401)
        if account_context(account) != account_context(g.account):
            raise AccountChanged("Votre compte ou votre session a changé.", 409)
        g.account = account
        yield connection


def account_info(account):
    own_workspace = account["workspace_id"] == account["own_workspace"]
    return {
        "username": account["username"],
        "owner": account["owner"],
        "personal": own_workspace,
        "code": account["share_code"] if own_workspace else None,
        "session_active": has_session(account),
        "site_name": account["site_name"] or SITE_NAME,
    }


def issue_login(connection, account_id):
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    connection.execute("DELETE FROM account_logins WHERE expires_at <= ? OR token_hash = ?", (now, login_digest()))
    connection.execute("INSERT INTO account_logins VALUES (?, ?, ?)", (digest, account_id, now + LOGIN_SECONDS))
    response = make_response("", 204)
    response.set_cookie(
        LOGIN_COOKIE, token, max_age=LOGIN_SECONDS, httponly=True, samesite="Lax", secure=request.is_secure,
    )
    response.delete_cookie(MAINTENANCE_COOKIE)
    device, _ = record_visit(connection, account_id)
    set_device_cookie(response, device)
    return response


def clear_login(response):
    response.delete_cookie(LOGIN_COOKIE, httponly=True, samesite="Lax", secure=request.is_secure)
    response.delete_cookie(MAINTENANCE_COOKIE)
    return response


def account_routes(database, json_input):
    blueprint = Blueprint("accounts", __name__, url_prefix="/api/account")
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
    attempts = {}
    attempt_lock = Lock()

    def limit_attempts(action, limit):
        now = time.monotonic()
        key = (action, request.remote_addr)
        with attempt_lock:
            for address, history in list(attempts.items()):
                while history and history[0] <= now - ATTEMPT_WINDOW:
                    history.popleft()
                if not history:
                    del attempts[address]
            history = attempts.setdefault(key, deque())
            if len(history) >= limit:
                raise InputError("Trop de tentatives. Réessayez dans quelques minutes.", 429)
            history.append(now)

    @blueprint.post("/register")
    def register():
        limit_attempts("register", 20)
        username, password = credentials(json_input())
        key = username_key(username)
        password_hash = generate_password_hash(password)
        with transaction(database, write=True) as connection:
            if connection.execute("SELECT 1 FROM accounts WHERE username_key = ?", (key,)).fetchone():
                raise InputError("Ce nom d’utilisateur est déjà pris.", 409)
            # Workspaces are retained after account deletion, so new accounts never reuse an ID.
            account = connection.execute(
                """INSERT INTO workspaces(id) VALUES ((
                       SELECT max((SELECT max(id) FROM workspaces), COALESCE((SELECT max(id) FROM accounts), 0)) + 1
                   ))""",
            ).lastrowid
            connection.execute(
                "INSERT INTO accounts(id, username, username_key, password_hash, own_workspace) VALUES (?, ?, ?, ?, ?)",
                (account, username, key, password_hash, account),
            )
            response = issue_login(connection, account)
        g.activity_user_id = account
        return response

    @blueprint.post("/login")
    def login():
        limit_attempts("login", 20)
        username, password = credentials(json_input())
        with transaction(database) as connection:
            account = connection.execute(
                "SELECT id, password_hash FROM accounts WHERE username_key = ?", (username_key(username),),
            ).fetchone()
        if not check_password_hash(account["password_hash"] if account else dummy_hash, password) or account is None:
            raise InputError("Nom d’utilisateur ou mot de passe incorrect.", 401)
        with transaction(database, write=True) as connection:
            if connection.execute("SELECT 1 FROM accounts WHERE id = ?", (account["id"],)).fetchone() is None:
                raise InputError("Nom d’utilisateur ou mot de passe incorrect.", 401)
            response = issue_login(connection, account["id"])
        g.activity_user_id = account["id"]
        return response

    @blueprint.post("/logout")
    def logout():
        with transaction(database, write=True) as connection:
            connection.execute("DELETE FROM account_logins WHERE token_hash = ?", (login_digest(),))
        return clear_login(make_response("", 204))

    @blueprint.post("/share")
    def share():
        with account_transaction(database, write=True) as connection:
            if g.account["joined_workspace"] is not None:
                raise InputError("Quittez d’abord la session rejointe.", 409)
            if g.account["share_code"] is None:
                while True:
                    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
                    if not connection.execute("SELECT 1 FROM workspaces WHERE share_code = ?", (code,)).fetchone():
                        break
                connection.execute("UPDATE workspaces SET share_code = ? WHERE id = ?", (code, g.workspace))
        return "", 204

    @blueprint.put("/site-name")
    def rename_site():
        name = text_value(json_input(), "name", "Nom affiché", length=40)
        if any(unicodedata.category(character) in {"Cc", "Cs"} for character in name):
            raise InputError("Saisissez le nom affiché sur une seule ligne.")
        with account_transaction(database, write=True) as connection:
            if not has_session(g.account):
                raise InputError("Créez ou rejoignez une session pour accéder aux réglages.", 403)
            connection.execute("UPDATE accounts SET site_name = ? WHERE id = ?", (name, g.account["id"]))
        return "", 204

    @blueprint.post("/join")
    def join():
        limit_attempts("join", 20)
        raw = json_input().get("code")
        code = raw.strip().upper() if isinstance(raw, str) else ""
        if len(code) != 8 or any(ch not in CODE_ALPHABET for ch in code):
            raise InputError("Saisissez le code de connexion à 8 caractères.")
        with account_transaction(database, write=True) as connection:
            if has_session(g.account):
                if g.account["joined_workspace"] is not None and g.account["share_code"] == code:
                    return "", 204
                raise InputError("Votre compte est déjà dans une session.", 409)
            workspace = connection.execute("SELECT id FROM workspaces WHERE share_code = ?", (code,)).fetchone()
            if workspace is None:
                raise InputError("Ce code ne correspond à aucune session active.", 404)
            connection.execute(
                "UPDATE accounts SET joined_workspace = ? WHERE id = ?", (workspace["id"], g.account["id"]),
            )
        return "", 204

    @blueprint.post("/leave")
    def leave():
        with account_transaction(database, write=True) as connection:
            if g.account["joined_workspace"] is None:
                raise InputError("Seuls les invités peuvent quitter une session.", 409)
            connection.execute("UPDATE accounts SET joined_workspace = NULL WHERE id = ?", (g.account["id"],))
        return "", 204

    return blueprint


def claim_existing(database, username):
    with transaction(database, write=True) as connection:
        account = connection.execute(
            """SELECT own_workspace, workspaces.share_code FROM accounts
               JOIN workspaces ON workspaces.id = own_workspace WHERE username_key = ?""",
            (username_key(username),),
        ).fetchone()
        if account is None:
            raise ValueError("Créez d’abord le compte qui doit récupérer les anciennes données.")
        workspace = account["own_workspace"]
        if account["share_code"] or any(connection.execute(
            f"SELECT 1 FROM {table} WHERE workspace_id = ? LIMIT 1", (workspace,),
        ).fetchone() for table in WORKSPACE_TABLES):
            raise ValueError("Choisissez un compte dont l’espace personnel est vide et privé.")
        moved = sum(connection.execute(
            f"UPDATE {table} SET workspace_id = ? WHERE workspace_id = 0", (workspace,),
        ).rowcount for table in WORKSPACE_TABLES)
        if moved == 0:
            raise ValueError("Aucune ancienne donnée à rattacher.")
