import socket
import time
import urllib.error
import urllib.request


def wait_for_http(host, port, timeout=10):
    """Vérifie que quelque chose écoute sur host:port."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def check_tcp_listener(host, port, timeout=2):
    """Vérifie qu'un port TCP accepte réellement une connexion."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, exc


def http_question_response(host, port, path="/", timeout=4):
    """Envoie une vraie requête HTTP et retourne (ok, status, raison)."""
    port = int(port)
    if not (1 <= port <= 65535):
        return False, None, "port invalide"
    if not path.startswith("/"):
        path = "/" + path
    url = f"http://{host}:{port}{path}"
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "Web-Deployer-Kit/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(64)
            status = response.getcode()
            return 200 <= status < 500, status, response.reason or "OK"
    except urllib.error.HTTPError as exc:
        # Une réponse HTTP 4xx prouve que le serveur répond : le transport fonctionne.
        return True, exc.code, exc.reason or "HTTP error"
    except Exception as exc:
        return False, None, str(exc)
