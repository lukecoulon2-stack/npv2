#!/usr/bin/env python3
"""Installe, initialise et démarre Planneli."""
import argparse
import errno
import hashlib
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from planning.config import CONFIG_FILE, PROJECT, read_config
from planning.database import DATABASE_NAME, backup, initialize, restore
from planning.updates import apply_pending, pending_revision


ENVIRONMENT = PROJECT / ".venv-planning"
REQUIREMENTS = PROJECT / "requirements.txt"


@contextmanager
def installation_lock():
    ENVIRONMENT.mkdir(exist_ok=True)
    with (ENVIRONMENT / ".install.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def environment_python():
    binary = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    stamp = ENVIRONMENT / ".requirements"
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    with installation_lock():
        if not (binary.is_file() and (ENVIRONMENT / "pyvenv.cfg").is_file()):
            print("Création de l’environnement Python…", flush=True)
            stamp.unlink(missing_ok=True)
            subprocess.run([sys.executable, "-m", "venv", str(ENVIRONMENT)], check=True)
        if not stamp.is_file() or stamp.read_text(encoding="utf-8") != digest:
            print("Installation des dépendances de Planneli…", flush=True)
            subprocess.run([str(binary), "-m", "ensurepip"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(
                [str(binary), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)],
                check=True,
            )
            stamp.write_text(digest, encoding="utf-8")
    return binary


def activate_environment():
    binary = environment_python()
    if Path(sys.prefix).resolve() != ENVIRONMENT.resolve():
        os.execv(str(binary), [str(binary), str(Path(__file__).resolve()), *sys.argv[1:]])


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # This selects the default interface without sending a packet.
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
    except OSError:
        return "IP-DE-CET-ORDINATEUR"


def url(host, port):
    address = f"[{host}]" if ":" in host else host
    return f"http://{address}:{port}/"


def serve(config, data_dir):
    from waitress import create_server

    from planning.library import PHOTO_REQUEST_LIMIT
    from planning.web import create_app

    database = data_dir / DATABASE_NAME
    app = create_app(database, config.mode)
    try:
        server = create_server(
            app, host=config.host, port=config.port, ident="Planneli",
            threads=4, max_request_body_size=PHOTO_REQUEST_LIMIT,
            trusted_proxy="127.0.0.1", trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
        )
    except socket.gaierror as error:
        raise ValueError(f"Adresse « host » impossible à résoudre : {config.host}.") from error
    except OSError as error:
        if error.errno in {errno.EADDRINUSE, 10048}:
            raise ValueError(
                f"Le port web {config.port} est déjà utilisé. Modifier « port » dans la configuration."
            ) from error
        raise
    try:
        initialize(database)
        local = {"0.0.0.0": "127.0.0.1", "::": "::1", "*": "127.0.0.1"}.get(config.host, config.host)
        print(f"Planneli · {url(local, config.port)}", flush=True)
        if config.host == "0.0.0.0":
            print(f"Sur le même Wi-Fi · {url(lan_address(), config.port)}", flush=True)
        if config.mode == "bench":
            print("Mode bench · Base temporaire vide pour ce lancement.", flush=True)
        else:
            print(f"Base locale · {database}", flush=True)
        print("Ctrl+C pour arrêter.", flush=True)
        server.run()
    finally:
        server.task_dispatcher.shutdown()
        server.close()


def stop_on_signal(_signum, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help="Utiliser un autre fichier JSON.")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument("--backup", type=Path, metavar="FICHIER", help="Créer une sauvegarde SQLite.")
    maintenance.add_argument("--restore", type=Path, metavar="FICHIER", help="Restaurer une sauvegarde SQLite.")
    maintenance.add_argument("--claim-existing", metavar="UTILISATEUR", help="Rattacher les anciennes données à ce compte.")
    args = parser.parse_args()

    try:
        if sys.version_info < (3, 10):
            raise ValueError("Planneli nécessite Python 3.10 ou une version ultérieure.")
        config = read_config(args.config.resolve())
        if args.backup or args.restore:
            if config.mode != "normal":
                raise ValueError("La sauvegarde et la restauration utilisent le mode normal.")
            database = config.data_dir / DATABASE_NAME
            if args.backup:
                target = args.backup.resolve()
                if target == database.resolve():
                    raise ValueError("Choisir une destination différente de la base active.")
                backup(database, target)
                print(f"Sauvegarde créée · {target}")
            else:
                previous = restore(args.restore.resolve(), database)
                print(f"Base restaurée · {database}")
                if previous:
                    print(f"Copie de la base précédente · {previous}")
            return 0

        if args.claim_existing is not None:
            if config.mode != "normal":
                raise ValueError("Le rattachement des anciennes données utilise le mode normal.")
            activate_environment()

            from planning.accounts import claim_existing

            database = config.data_dir / DATABASE_NAME
            initialize(database)
            claim_existing(database, args.claim_existing)
            print(f"Anciennes données rattachées · {args.claim_existing}")
            return 0

        if config.mode == "normal":
            with installation_lock():
                if pending_revision(PROJECT):
                    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(config.host, config.host)
                    try:
                        connection = socket.create_connection((host, config.port), timeout=0.5)
                    except OSError:
                        pass
                    else:
                        connection.close()
                        raise ValueError("Arrêtez le serveur en cours avant d’appliquer la mise à jour.")
                revision = apply_pending(PROJECT)
            if revision:
                print(f"Mise à jour Planneli appliquée · {revision[:12]}", flush=True)
                os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

        activate_environment()
        signal.signal(signal.SIGTERM, stop_on_signal)
        if config.mode == "bench":
            with tempfile.TemporaryDirectory(prefix="tempo-bench-") as directory:
                serve(config, Path(directory))
        else:
            serve(config, config.data_dir)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, sqlite3.Error, subprocess.CalledProcessError) as error:
        print(f"Planneli · {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
