import http.client
import socket
import ssl
import time


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


def http_question_response(
    host,
    port,
    path="/",
    timeout=4,
    expected_status=None,
    https=False,
    server_hostname=None,
):
    """Envoie une vraie requête HTTP et retourne (ok, status, raison)."""
    port = int(port)
    if not (1 <= port <= 65535):
        return False, None, "port invalide"
    if not path.startswith("/"):
        path = "/" + path
    connection = None
    try:
        if https:
            connection = http.client.HTTPSConnection(
                host,
                port,
                timeout=timeout,
                context=ssl.create_default_context(),
                server_hostname=server_hostname,
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
        headers = {"User-Agent": "Web-Deployer-Kit/1.0"}
        if server_hostname:
            headers["Host"] = server_hostname
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        response.read(64)
        status = response.status
        reason = response.reason or "OK"
        if expected_status is not None:
            expected_status = int(expected_status)
            return status == expected_status, status, reason
        return 200 <= status < 500, status, reason
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return False, None, str(exc)
    finally:
        if connection is not None:
            connection.close()
