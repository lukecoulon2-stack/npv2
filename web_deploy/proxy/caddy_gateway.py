import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from web_deploy.core.health import check_tcp_listener
from web_deploy.security.access_control import AccessController, AccessPolicy


class CaddyGateway:
    def __init__(
        self,
        domain,
        target_host,
        target_port,
        log=print,
        access_policy=None,
        executable=None,
        listen_port=443,
        https=None,
        auth_enabled=False,
        health_path="/",
        health_status=200,
        health_interval=10,
        health_timeout=3,
        listen_host="0.0.0.0",
    ):
        self.https = bool(domain) if https is None else bool(https)
        self.domain = self.validate_domain(domain) if self.https else None
        self.target_host = target_host
        self.target_port = int(target_port)
        self.listen_port = int(listen_port)
        self.listen_host = str(listen_host)
        if self.listen_host not in ("0.0.0.0", "127.0.0.1", "localhost"):
            raise ValueError("Adresse d'écoute Caddy non autorisée.")
        if not 1 <= self.listen_port <= 65535:
            raise ValueError("Port d'écoute Caddy invalide.")
        if self.https and self.listen_port != 443:
            raise ValueError("Le mode HTTPS Caddy doit écouter sur le port 443.")
        self.log = log
        self.access_policy = access_policy
        self.auth_enabled = bool(auth_enabled)
        self.health_path = self.validate_health_path(health_path)
        self.health_status = int(health_status)
        self.health_interval = max(1, int(health_interval))
        self.health_timeout = max(1, int(health_timeout))
        if not 200 <= self.health_status <= 599:
            raise ValueError("Le code de santé HTTP doit être compris entre 200 et 599.")
        self.executable = (
            executable
            or os.environ.get("WEB_DEPLOY_CADDY")
            or shutil.which("caddy")
        )
        self.process = None
        self.output_thread = None
        self.config_dir = None
        self.access_controller = None

    @staticmethod
    def validate_domain(domain):
        domain = str(domain or "").strip().rstrip(".")
        try:
            normalized = domain.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("Nom de domaine invalide.") from exc
        if len(normalized) > 253 or "." not in normalized:
            raise ValueError("Saisissez un nom de domaine public complet.")
        labels = normalized.split(".")
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            raise ValueError("Nom de domaine invalide.")
        return normalized

    @staticmethod
    def validate_health_path(path):
        path = str(path or "/").strip()
        if not path.startswith("/") or "\n" in path or "\r" in path:
            raise ValueError("Le chemin du health check doit commencer par /.")
        return path

    @staticmethod
    def render_caddyfile(
        domain,
        upstream_port,
        auth_port,
        listen_port=443,
        https=True,
        auth_enabled=False,
        health_path="/",
        health_status=200,
        health_interval=10,
        health_timeout=3,
        listen_host="0.0.0.0",
    ):
        domain = CaddyGateway.validate_domain(domain) if https else None
        upstream_port = int(upstream_port)
        auth_port = int(auth_port)
        listen_port = int(listen_port)
        health_status = int(health_status)
        health_interval = max(1, int(health_interval))
        health_timeout = max(1, int(health_timeout))
        health_path = CaddyGateway.validate_health_path(health_path)
        listen_host = str(listen_host)
        if listen_host not in ("0.0.0.0", "127.0.0.1", "localhost"):
            raise ValueError("Adresse d'écoute Caddy non autorisée.")
        if not 1 <= upstream_port <= 65535 or not 1 <= auth_port <= 65535:
            raise ValueError("Port upstream invalide.")
        if not 1 <= listen_port <= 65535:
            raise ValueError("Port d'écoute Caddy invalide.")
        if https and listen_port != 443:
            raise ValueError("Le mode HTTPS Caddy doit écouter sur le port 443.")
        if not 200 <= health_status <= 599:
            raise ValueError("Code de health check invalide.")

        site_address = domain if https else (
            f":{listen_port}" if listen_host == "0.0.0.0" else f"{listen_host}:{listen_port}"
        )
        authorization_header = "        header_up -Authorization\n" if auth_enabled else ""
        return (
            "{\n"
            "    admin off\n"
            "}\n\n"
            f"{site_address} {{\n"
            f"    forward_auth 127.0.0.1:{auth_port} {{\n"
            "        uri /authorize\n"
            "        header_up X-Web-Deploy-Request-Bytes {http.request.header.Content-Length}\n"
            "        header_up X-Web-Deploy-Method {http.request.method}\n"
            "    }\n"
            f"    reverse_proxy 127.0.0.1:{upstream_port} {{\n"
            "        flush_interval -1\n"
            f"        health_uri {health_path}\n"
            f"        health_interval {health_interval}s\n"
            f"        health_timeout {health_timeout}s\n"
            f"        health_status {health_status}\n"
            f"{authorization_header}"
            "    }\n"
            "}\n"
        )

    def verify_binary(self):
        if not self.executable:
            raise RuntimeError(
                "Caddy v2 est requis comme proxy. Installe Caddy ou définis WEB_DEPLOY_CADDY."
            )
        try:
            result = subprocess.run(
                [self.executable, "version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Impossible de vérifier le binaire Caddy : {exc}") from exc
        version_text = result.stdout + result.stderr
        match = re.search(r"\bv2\.\d+\.\d+", version_text)
        if result.returncode != 0 or not match:
            raise RuntimeError("Caddy v2 est requis. Vérifie le binaire WEB_DEPLOY_CADDY.")
        return match.group(0)

    def start(self, timeout=15):
        if self.process and self.process.poll() is None:
            return

        try:
            self.verify_binary()
            self.access_controller = AccessController(
                self.access_policy or AccessPolicy(max_requests=0), self.log
            )
            auth_port = self.access_controller.start()
            self.config_dir = Path(tempfile.mkdtemp(prefix="web_deployer_caddy_"))
            config_path = self.config_dir / "Caddyfile"
            config_path.write_text(
                self.render_caddyfile(
                    self.domain,
                    self.target_port,
                    auth_port,
                    listen_port=self.listen_port,
                    https=self.https,
                    auth_enabled=self.auth_enabled,
                    health_path=self.health_path,
                    health_status=self.health_status,
                    health_interval=self.health_interval,
                    health_timeout=self.health_timeout,
                    listen_host=self.listen_host,
                ),
                encoding="utf-8",
            )
            if os.name != "nt":
                os.chmod(config_path, 0o600)
            validation = subprocess.run(
                [
                    self.executable,
                    "validate",
                    "--config",
                    str(config_path),
                    "--adapter",
                    "caddyfile",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if validation.returncode != 0:
                details = (validation.stderr or validation.stdout).strip()
                raise RuntimeError(f"Configuration Caddy invalide : {details}")
        except Exception:
            try:
                self.stop(force=True)
            except Exception as cleanup_error:
                self.log(f"[ERREUR] Nettoyage Caddy incomplet : {cleanup_error}")
            raise

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        try:
            self.process = subprocess.Popen(
                [self.executable, "run", "--config", str(config_path), "--adapter", "caddyfile"],
                **kwargs,
            )
            self.output_thread = threading.Thread(
                target=self._read_output,
                args=(self.process,),
                name="web-deployer-caddy-output",
                daemon=True,
            )
            self.output_thread.start()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("Caddy s'est arrêté pendant son démarrage.")
                listening, _error = check_tcp_listener(
                    "127.0.0.1", self.listen_port, timeout=0.25
                )
                if listening:
                    scheme = "https" if self.https else "http"
                    address = self.domain if self.https else f"{self.listen_host}:{self.listen_port}"
                    self.log(f"[OK] Caddy écoute sur {scheme}://{address}.")
                    return
                threading.Event().wait(0.2)
            raise TimeoutError(
                f"Caddy n'a pas ouvert le port {self.listen_port} dans le délai prévu."
            )
        except Exception:
            try:
                self.stop(force=True)
            except Exception as cleanup_error:
                self.log(f"[ERREUR] Nettoyage Caddy incomplet : {cleanup_error}")
            raise

    def _read_output(self, process):
        if process.stdout:
            for line in process.stdout:
                self.log("[CADDY] " + line.rstrip())

    def stop(self, force=False, timeout=5):
        errors = []
        process = self.process
        if process and process.poll() is None:
            try:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if not force:
                        raise
                    process.kill()
                    process.wait(timeout=2)
            except Exception as exc:
                errors.append(f"Caddy: {exc}")

        if self.access_controller is not None and (process is None or process.poll() is not None):
            try:
                self.access_controller.stop()
                self.access_controller = None
            except Exception as exc:
                errors.append(f"service d'autorisation: {exc}")

        if process is None or process.poll() is not None:
            self.process = None
            if self.output_thread and self.output_thread is not threading.current_thread():
                self.output_thread.join(timeout=1)
            self.output_thread = None
            if self.config_dir:
                shutil.rmtree(self.config_dir, ignore_errors=True)
                self.config_dir = None

        if errors:
            raise RuntimeError("; ".join(errors))