"""Libération contrôlée des ports sélectionnés avant un déploiement."""
import csv
import os
import re
import socket
import subprocess


def _pids_with_lsof(port):
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    pids = []
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
            if pid > 0 and pid != os.getpid():
                pids.append(pid)
        except ValueError:
            pass
    return sorted(set(pids))


def _pids_with_fuser(port):
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    pids = []
    for match in re.findall(r"\b\d+\b", result.stdout):
        pid = int(match)
        if pid > 0 and pid != os.getpid():
            pids.append(pid)
    return sorted(set(pids))


def find_port_pids(port):
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, check=False, timeout=3,
            )
            pids = []
            wanted = f":{port}"
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].upper().startswith("TCP") and wanted in parts[1] and parts[3].upper() == "LISTENING":
                    try:
                        pid = int(parts[-1])
                        if pid and pid != os.getpid():
                            pids.append(pid)
                    except ValueError:
                        pass
            return sorted(set(pids))
        except (FileNotFoundError, subprocess.SubprocessError):
            return []
    pids = _pids_with_lsof(port)
    if pids:
        return pids
    pids = _pids_with_fuser(port)
    if pids:
        return pids
    # Dernier recours Linux : ss est généralement présent même sans lsof/fuser.
    if os.name != "nt":
        try:
            result = subprocess.run(
                ["ss", "-ltnp", f"sport = :{port}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, check=False, timeout=3,
            )
            found = []
            for pid_text in re.findall(r"pid=(\d+)", result.stdout):
                pid = int(pid_text)
                if pid > 0 and pid != os.getpid():
                    found.append(pid)
            return sorted(set(found))
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    return []


def _process_name(pid):
    if os.name == "nt":
        command = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    else:
        command = ["ps", "-p", str(pid), "-o", "comm="]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    if os.name == "nt":
        rows = list(csv.reader(result.stdout.splitlines()))
        if rows and len(rows[0]) > 1 and rows[0][1].isdigit():
            return rows[0][0]
        return None
    name = result.stdout.strip()
    return name or None


def port_is_free(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def clear_port(port, log=print, label="port"):
    """Vérifie *port* sans arrêter de processus qui n'appartient pas au kit."""
    port = int(port)
    pids = find_port_pids(port)
    if pids:
        descriptions = []
        for pid in pids:
            name = _process_name(pid)
            descriptions.append(f"{pid} ({name})" if name else str(pid))
        pid_list = ", ".join(descriptions)
        log(
            f"[ERREUR] Port {port} ({label}) déjà utilisé par le(s) PID {pid_list}. "
            "Aucun processus externe n'a été arrêté ; choisis un autre port."
        )
        return False

    if not port_is_free("0.0.0.0", port):
        log(
            f"[ERREUR] Port {port} ({label}) indisponible, mais le processus n'a pas pu être identifié. "
            "Aucun processus n'a été arrêté ; choisis un autre port."
        )
        return False

    log(f"[OK] Port {port} ({label}) libre.")
    return True
