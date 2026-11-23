import hashlib
import re
import secrets

from flask import request

from .rules import now_iso


DEVICE_COOKIE = "naoning_device"


def record_visit(connection, account_id=None):
    device = request.cookies.get(DEVICE_COOKIE, "")
    issued = None
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", device):
        device = issued = secrets.token_urlsafe(32)
    identity = device if account_id is None else f"{account_id}:{device}"
    digest = hashlib.sha256(identity.encode("ascii")).hexdigest()
    ip = request.remote_addr or "inconnue"
    visitor = connection.execute("SELECT id FROM visitors WHERE ip = ? AND device = ?", (ip, digest)).fetchone()
    first = visitor is None
    visitor_id = connection.execute(
        "INSERT INTO visitors(ip, device, account_id) VALUES (?, ?, ?)", (ip, digest, account_id),
    ).lastrowid if first else visitor["id"]
    connection.execute("INSERT INTO connections(visitor_id, connected_at) VALUES (?, ?)", (visitor_id, now_iso()))
    return issued, first


def set_device_cookie(response, device):
    if device:
        response.set_cookie(
            DEVICE_COOKIE, device, max_age=400 * 86400, httponly=True, samesite="Lax", secure=request.is_secure,
        )
