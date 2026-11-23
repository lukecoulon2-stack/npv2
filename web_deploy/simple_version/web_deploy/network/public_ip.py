from urllib.request import Request, urlopen


def get_public_ip():
    """Détecte l'adresse IPv4 publique de la connexion Internet."""
    services = (
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://checkip.amazonaws.com",
    )
    last_error = None
    for url in services:
        try:
            request = Request(url, headers={"User-Agent": "Web-Deployer/1.0"})
            with urlopen(request, timeout=4) as response:
                ip = response.read().decode("utf-8").strip()
            if ip:
                return ip
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return None
