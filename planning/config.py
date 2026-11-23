from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT / "planning_config_starter.json"
DEFAULT_ZONE = "Europe/Paris"
SITE_NAME = "Planneli"


def default_data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "planning-familial"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "planning-familial"
    xdg = Path(os.environ.get("XDG_DATA_HOME", ""))
    base = xdg if xdg.is_absolute() else Path.home() / ".local" / "share"
    return base / "planning-familial"


@dataclass(frozen=True)
class LaunchConfig:
    mode: str
    host: str
    port: int
    data_dir: Path | None


def read_config(path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} — JSON invalide, ligne {error.lineno}, colonne {error.colno}.") from error
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{path} — lecture impossible ({error}).") from error

    def invalid(key, message):
        raise ValueError(f"{path} — {key} : {message}")

    if not isinstance(raw, dict):
        invalid("configuration", "un objet JSON est attendu.")
    allowed = {"mode", "host", "port", "data_dir"}
    for key in sorted(allowed - raw.keys()):
        invalid(key, "ce réglage est obligatoire.")
    for key in sorted(raw.keys() - allowed):
        invalid(key, "réglage inconnu.")

    mode, host, port, directory = (raw[key] for key in ("mode", "host", "port", "data_dir"))
    if mode not in ("normal", "bench"):
        invalid("mode", 'choisir "normal" ou "bench".')
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.:%_-]{1,253}", host):
        invalid("host", "indiquer une adresse IP ou un nom d’hôte.")
    if type(port) is not int or not 1 <= port <= 65535:
        invalid("port", "indiquer un entier entre 1 et 65535.")
    if directory is not None and (
        not isinstance(directory, str) or "\x00" in directory or not Path(directory).is_absolute()
    ):
        invalid("data_dir", "indiquer un chemin absolu ou null.")

    data_dir = None
    if mode == "normal":
        try:
            data_dir = (Path(directory) if directory is not None else default_data_dir()).resolve()
        except (OSError, RuntimeError) as error:
            invalid("data_dir", str(error))
        if data_dir.is_relative_to(PROJECT):
            invalid("data_dir", "choisir un dossier en dehors du projet.")
    return LaunchConfig(mode, host, port, data_dir)
