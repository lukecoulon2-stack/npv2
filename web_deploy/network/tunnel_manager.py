import os
import re
import shutil
import signal
import subprocess
import threading
import time


_QUICK_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


class TunnelManager:
    def __init__(self, log=print, executable=None):
        self.log = log
        self.executable = (
            executable
            or os.environ.get("WEB_DEPLOY_CLOUDFLARED")
            or shutil.which("cloudflared")
        )
        self.process = None
        self.output_thread = None
        self._url_ready = threading.Event()
        self._url_lock = threading.Lock()
        self.public_url = None

    def verify_binary(self):
        if not self.executable:
            raise RuntimeError(
                "cloudflared est requis pour le tunnel. Installe cloudflared ou définis WEB_DEPLOY_CLOUDFLARED."
            )
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Impossible de vérifier cloudflared : {exc}") from exc
        if result.returncode != 0 or "cloudflared" not in (result.stdout + result.stderr).lower():
            raise RuntimeError("Le binaire configuré n'est pas cloudflared.")
        return (result.stdout or result.stderr).strip().splitlines()[0]

    def start(self, local_port, timeout=30):
        if self.process and self.process.poll() is None:
            return self.public_url
        self.verify_binary()
        self._url_ready.clear()
        self.public_url = None
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
                [
                    self.executable,
                    "tunnel",
                    "--no-autoupdate",
                    "--url",
                    f"http://127.0.0.1:{int(local_port)}",
                ],
                **kwargs,
            )
        except OSError as exc:
            raise RuntimeError(f"Impossible de démarrer cloudflared : {exc}") from exc

        self.output_thread = threading.Thread(
            target=self._read_output,
            args=(self.process,),
            name="web-deployer-cloudflared-output",
            daemon=True,
        )
        self.output_thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._url_ready.wait(0.1):
                return self.public_url
            if self.process.poll() is not None:
                break

        try:
            self.stop(force=True)
        except Exception as exc:
            self.log(f"[ERREUR] Arrêt cloudflared incomplet : {exc}")
        raise RuntimeError(
            "cloudflared n'a pas fourni d'URL Quick Tunnel. Vérifie la connexion sortante et les restrictions réseau."
        )

    def _read_output(self, process):
        if not process.stdout:
            return
        for line in process.stdout:
            line = line.rstrip()
            self.log("[CLOUDFLARED] " + line)
            match = _QUICK_TUNNEL_URL.search(line)
            if match:
                with self._url_lock:
                    self.public_url = match.group(0)
                self._url_ready.set()

    def stop(self, force=False, timeout=5):
        process = self.process
        if process and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if not force:
                    raise
                process.kill()
                process.wait(timeout=2)

        if process is None or process.poll() is not None:
            self.process = None
            self.public_url = None
            output_thread = self.output_thread
            self.output_thread = None
            if output_thread and output_thread is not threading.current_thread():
                output_thread.join(timeout=1)