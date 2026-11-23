"""Libération contrôlée des ports sélectionnés avant un déploiement."""
import os
import re
import signal
import socket
import subprocess
import time


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
    """Arrête les processus qui écoutent sur *port* puis vérifie sa disponibilité."""
    port = int(port)
    pids = find_port_pids(port)
    if not pids:
        log(f"[OK] Port {port} ({label}) déjà libre.")
        return True

    log(f"[INFO] Nettoyage du port {port} ({label}) : processus détecté(s) {', '.join(map(str, pids))}.")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            log(f"[INFO] Arrêt du processus {pid} demandé.")
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            log(f"[ERREUR] Impossible d'arrêter le processus {pid} : {exc}")
            return False

    deadline = time.time() + 3
    while time.time() < deadline:
        if not find_port_pids(port):
            log(f"[OK] Port {port} libéré.")
            return True
        time.sleep(0.15)

    # Dernier recours : SIGKILL sous Unix / taskkill forcé sous Windows.
    remaining = find_port_pids(port)
    for pid in remaining:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                os.kill(pid, signal.SIGKILL)
            log(f"[WARN] Processus {pid} forcé à s'arrêter.")
        except (ProcessLookupError, PermissionError):
            pass

    time.sleep(0.2)
    if find_port_pids(port):
        log(f"[ERREUR] Le port {port} ({label}) reste occupé.")
        return False
    log(f"[OK] Port {port} libéré après arrêt forcé.")
    return True
