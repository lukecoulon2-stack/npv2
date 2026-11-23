import os
import subprocess
import sys
import tempfile
from pathlib import Path


class ServerLauncher:
    """Lance l'application en imposant le host/port configurés.

    Certaines applications Flask appellent ``app.run(port=8000)`` en dur.
    Dans ce cas, les variables HOST/PORT seules ne suffisent pas. On injecte
    un petit ``sitecustomize`` dans PYTHONPATH qui force Flask à utiliser la
    configuration de Web Deployer.
    """

    def __init__(self, script, host, port, log=print, python_executable=None):
        self.script = script
        self.host = host
        self.port = int(port)
        self.log = log
        self.process = None
        self.python_executable = python_executable or sys.executable
        self._shim_dir = None

    def _create_port_shim(self):
        shim_dir = Path(tempfile.mkdtemp(prefix="web_deployer_shim_"))
        shim = shim_dir / "sitecustomize.py"
        shim.write_text(
            '''import os\n\n\n# Web Deployer impose le port configure meme si app.run()\n# contient un port en dur dans le projet.\nif os.environ.get("WEB_DEPLOY_FORCE_PORT") == "1":\n    try:\n        from flask import Flask\n        _web_deployer_original_run = Flask.run\n\n        def _web_deployer_run(self, *args, **kwargs):\n            kwargs["host"] = os.environ.get("WEB_DEPLOY_HOST", kwargs.get("host", "127.0.0.1"))\n            kwargs["port"] = int(os.environ["WEB_DEPLOY_PORT"])\n            return _web_deployer_original_run(self, *args, **kwargs)\n\n        Flask.run = _web_deployer_run\n    except Exception:\n        pass\n''',
            encoding="utf-8",
        )
        self._shim_dir = shim_dir
        return shim_dir

    def start(self):
        if self.process and self.process.poll() is None:
            self.log("[INFO] Le serveur est déjà lancé.")
            return

        env = os.environ.copy()
        env["HOST"] = self.host
        env["PORT"] = str(self.port)
        env["WEB_DEPLOY_HOST"] = self.host
        env["WEB_DEPLOY_PORT"] = str(self.port)
        env["WEB_DEPLOY_FORCE_PORT"] = "1"

        shim_dir = self._create_port_shim()
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(shim_dir)
            if not current_pythonpath
            else str(shim_dir) + os.pathsep + current_pythonpath
        )

        self.log(f"[INFO] Python utilisé : {self.python_executable}")
        self.log(f"[INFO] Port serveur imposé par Web Deployer : {self.host}:{self.port}")

        script_path = Path(self.script).resolve()
        if not script_path.is_file():
            raise FileNotFoundError(f"Script serveur introuvable : {script_path}")

        kwargs = dict(
            cwd=str(script_path.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        self.process = subprocess.Popen(
            [self.python_executable, str(script_path)],
            **kwargs,
        )

        import threading
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.log("[APP] " + line.rstrip())


    def stop(self, timeout=4):
        process = self.process
        if not process or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        finally:
            self.process = None
            if self._shim_dir:
                import shutil
                shutil.rmtree(self._shim_dir, ignore_errors=True)
                self._shim_dir = None
