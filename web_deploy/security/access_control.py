import base64
import binascii
from contextlib import closing
import hmac
import ipaddress
import math
import os
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class AccessPolicy:
    def __init__(
        self,
        allowed_ip_ranges=(),
        max_requests=120,
        window_seconds=60,
        clock=None,
        auth_credentials=None,
        daily_upload_limit_bytes=None,
        usage_db_path=None,
        utc_now=None,
    ):
        if isinstance(allowed_ip_ranges, str):
            allowed_ip_ranges = allowed_ip_ranges.split(",")
        try:
            self.allowed_networks = tuple(
                ipaddress.ip_network(value, strict=False)
                for value in allowed_ip_ranges
                if str(value).strip()
            )
        except ValueError as exc:
            raise ValueError(f"Plage IP invalide : {exc}") from exc

        self.max_requests = int(max_requests)
        self.window_seconds = int(window_seconds)
        if self.max_requests < 0:
            raise ValueError("La limite de requêtes ne peut pas être négative.")
        if self.window_seconds < 1:
            raise ValueError("La fenêtre de limitation doit durer au moins une seconde.")
        self.auth_credentials = auth_credentials
        if auth_credentials is not None:
            username = str(auth_credentials.get("username", ""))
            password = str(auth_credentials.get("password", ""))
            if not username or ":" in username or not password:
                raise ValueError("Identifiant ou mot de passe Basic invalide.")
            self._auth_username = username
            self._auth_password = password
        else:
            self._auth_username = None
            self._auth_password = None
        self.daily_upload_limit_bytes = (
            int(daily_upload_limit_bytes)
            if daily_upload_limit_bytes is not None
            else None
        )
        if self.daily_upload_limit_bytes is not None:
            if self.daily_upload_limit_bytes < 1:
                raise ValueError("Le quota quotidien doit être supérieur à zéro octet.")
            self.usage_db_path = Path(
                usage_db_path
                or Path.home() / ".web_deploy_kit" / "security_usage.sqlite3"
            )
            self.usage_db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.usage_db_path, timeout=5)) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS daily_upload_usage ("
                    "utc_day TEXT PRIMARY KEY, bytes INTEGER NOT NULL CHECK(bytes >= 0))"
                )
                connection.commit()
            if os.name != "nt":
                os.chmod(self.usage_db_path, 0o600)
            self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        else:
            self.usage_db_path = None
            self._utc_now = None

        self._clock = clock or time.monotonic
        self._requests_by_ip = OrderedDict()
        self._lock = threading.Lock()

    def check(
        self,
        client_ip,
        authorization=None,
        request_bytes=None,
        method="GET",
    ):
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return 403, None

        if self.allowed_networks and not any(
            address.version == network.version and address in network
            for network in self.allowed_networks
        ):
            return 403, None

        if self.max_requests == 0:
            retry_after = None
        else:
            now = self._clock()
            window_start = now - self.window_seconds
            with self._lock:
                requests = self._requests_by_ip.get(address)
                if requests is None:
                    requests = deque()
                    self._requests_by_ip[address] = requests
                else:
                    self._requests_by_ip.move_to_end(address)
                while requests and requests[0] <= window_start:
                    requests.popleft()
                if len(requests) >= self.max_requests:
                    retry_after = max(1, math.ceil(requests[0] + self.window_seconds - now))
                    return 429, retry_after
                requests.append(now)
                while len(self._requests_by_ip) > 10000:
                    self._requests_by_ip.popitem(last=False)

        if self.auth_credentials is not None and not self._authorized(authorization):
            return 401, None

        if self.daily_upload_limit_bytes is not None:
            return self._reserve_daily_upload(request_bytes, method)

        return None, None

    def _reserve_daily_upload(self, request_bytes, method):
        if request_bytes is None:
            if str(method).upper() not in {"GET", "HEAD", "OPTIONS"}:
                return 411, None
            request_bytes = 0
        try:
            request_bytes = int(request_bytes)
        except (TypeError, ValueError):
            return 400, None
        if request_bytes < 0:
            return 400, None

        now = self._utc_now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        utc_day = now.date().isoformat()
        next_midnight = datetime.combine(
            now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        )
        retry_after = max(1, math.ceil((next_midnight - now).total_seconds()))

        try:
            with closing(sqlite3.connect(self.usage_db_path, timeout=5)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT bytes FROM daily_upload_usage WHERE utc_day = ?",
                    (utc_day,),
                ).fetchone()
                used_bytes = row[0] if row else 0
                if used_bytes + request_bytes > self.daily_upload_limit_bytes:
                    connection.rollback()
                    return 429, retry_after
                connection.execute(
                    "INSERT INTO daily_upload_usage (utc_day, bytes) VALUES (?, ?) "
                    "ON CONFLICT(utc_day) DO UPDATE SET bytes = excluded.bytes",
                    (utc_day, used_bytes + request_bytes),
                )
                connection.commit()
        except sqlite3.Error:
            return 503, None
        return None, None

    def _authorized(self, authorization):
        if not isinstance(authorization, str):
            return False
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "basic":
            return False
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        username, separator, password = decoded.partition(":")
        if not separator:
            return False
        username_matches = hmac.compare_digest(
            username.encode("utf-8"), self._auth_username.encode("utf-8")
        )
        password_matches = hmac.compare_digest(
            password.encode("utf-8"), self._auth_password.encode("utf-8")
        )
        return bool(username_matches & password_matches)


class AccessController:
    def __init__(self, policy, log=print):
        self.policy = policy
        self.log = log
        self.server = None
        self.thread = None

    def start(self):
        if self.server is not None:
            return self.server.server_address[1]

        policy = self.policy

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                forwarded_for = self.headers.get("X-Forwarded-For", "")
                client_ip = forwarded_for.split(",", 1)[0].strip()
                if not client_ip:
                    client_ip = self.client_address[0]
                request_bytes = self.headers.get("X-Web-Deploy-Request-Bytes")
                if request_bytes == "":
                    request_bytes = None
                method = self.headers.get("X-Web-Deploy-Method", "GET")
                status, retry_after = policy.check(
                    client_ip,
                    self.headers.get("Authorization"),
                    request_bytes=request_bytes,
                    method=method,
                )
                if status is None:
                    self.send_response(204)
                elif status == 401:
                    self.send_response(401, "Unauthorized")
                    self.send_header("WWW-Authenticate", 'Basic realm="Web Deploy Kit"')
                elif status == 429:
                    self.send_response(429, "Too Many Requests")
                    self.send_header("Retry-After", str(retry_after))
                elif status == 411:
                    self.send_response(411, "Length Required")
                elif status == 503:
                    self.send_response(503, "Upload quota unavailable")
                else:
                    self.send_response(403, "Forbidden")
                self.end_headers()

            def log_message(self, _format, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="web-deployer-access-controller",
            daemon=True,
        )
        self.thread.start()
        return self.server.server_address[1]

    def stop(self):
        server = self.server
        thread = self.thread
        if server is not None:
            server.shutdown()
            server.server_close()
            self.server = None
        if thread is not None:
            if thread is not threading.current_thread():
                thread.join(timeout=2)
            if thread.is_alive():
                raise RuntimeError("Le service d'autorisation ne s'est pas arrêté.")
            self.thread = None