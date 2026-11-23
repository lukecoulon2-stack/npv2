import ipaddress
import re
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkFinding:
    level: str
    title: str
    detail: str
    next_step: str


@dataclass(frozen=True)
class DNSCheckResult:
    domain: str
    addresses: tuple[str, ...]
    expected_ip: str | None

    @property
    def matches(self):
        return self.expected_ip is None or self.expected_ip in self.addresses


def resolve_domain(domain, expected_ip=None):
    domain = str(domain or "").strip().rstrip(".").lower()
    labels = domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("Saisissez un nom de domaine public valide.")

    normalized_expected = None
    if expected_ip:
        try:
            normalized_expected = str(ipaddress.ip_address(expected_ip))
        except ValueError as exc:
            raise ValueError("L'adresse IP publique attendue est invalide.") from exc

    try:
        records = socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Le domaine ne se résout pas : {exc}") from exc
    addresses = tuple(sorted({str(ipaddress.ip_address(record[4][0])) for record in records}))
    if not addresses:
        raise ValueError("Aucune adresse IP n'a été trouvée pour ce domaine.")
    return DNSCheckResult(domain, addresses, normalized_expected)


def diagnose_network(local_ip=None, public_ip=None, router_wan_ip=None, proxy_listening=None):
    findings = []
    public_address = None
    if public_ip:
        try:
            public_address = ipaddress.ip_address(public_ip)
        except ValueError:
            findings.append(NetworkFinding(
                "warning", "IP publique invalide", "La valeur détectée n'est pas une adresse IP valide.",
                "Relance la détection de l'IP publique.",
            ))
        else:
            shared_cgnat = ipaddress.ip_network("100.64.0.0/10")
            if public_address in shared_cgnat:
                findings.append(NetworkFinding(
                    "warning", "CGNAT probable", f"L'adresse {public_address} appartient à la plage partagée CGNAT.",
                    "Une redirection NAT classique peut être impossible ; utilise un tunnel ou contacte le fournisseur.",
                ))
            elif public_address.is_private or public_address.is_loopback or public_address.is_link_local:
                findings.append(NetworkFinding(
                    "warning", "Adresse non publique", f"L'adresse détectée {public_address} n'est pas publique.",
                    "Vérifie le CGNAT, le double NAT ou la réponse du service de détection.",
                ))
            else:
                findings.append(NetworkFinding(
                    "ok", "IP publique détectée", f"Adresse publique : {public_address}.",
                    "Compare-la à l'adresse WAN affichée dans le routeur.",
                ))
    else:
        findings.append(NetworkFinding(
            "warning", "IP publique indisponible", "Aucune IP publique n'a été détectée.",
            "Vérifie la connexion Internet ou la détection d'adresse publique.",
        ))

    if local_ip:
        findings.append(NetworkFinding(
            "ok", "IP locale détectée", f"Adresse de cette machine : {local_ip}.",
            "Utilise cette adresse comme destination LAN dans la redirection NAT.",
        ))
    else:
        findings.append(NetworkFinding(
            "warning", "IP locale indisponible", "L'adresse de cette machine n'a pas été détectée.",
            "Vérifie l'interface réseau et l'adresse à réserver dans le DHCP.",
        ))

    if router_wan_ip:
        try:
            router_address = ipaddress.ip_address(router_wan_ip)
        except ValueError:
            findings.append(NetworkFinding(
                "warning", "IP WAN du routeur invalide", "La valeur saisie n'est pas une adresse IP valide.",
                "Recopie l'adresse WAN affichée par le routeur.",
            ))
        else:
            if router_address in ipaddress.ip_network("100.64.0.0/10"):
                findings.append(NetworkFinding(
                    "warning", "CGNAT probable", f"L'IP WAN du routeur ({router_address}) est dans la plage CGNAT.",
                    "Demande une IP publique au fournisseur ou utilise un tunnel sortant.",
                ))
            elif router_address.is_private or router_address.is_link_local:
                findings.append(NetworkFinding(
                    "warning", "Double NAT probable", f"L'IP WAN du routeur ({router_address}) est privée.",
                    "Une seconde box/modem est probablement en amont ; configure le NAT sur les deux équipements ou utilise un tunnel.",
                ))
            elif public_address and router_address != public_address:
                findings.append(NetworkFinding(
                    "warning", "IP WAN différente", f"Routeur : {router_address} ; IP détectée : {public_address}.",
                    "Vérifie le double NAT, le proxy du fournisseur ou un changement récent d'IP.",
                ))
            else:
                findings.append(NetworkFinding(
                    "ok", "IP WAN cohérente", "L'IP WAN du routeur correspond à l'IP publique détectée.",
                    "La redirection NAT peut être configurée sur ce routeur.",
                ))
    else:
        findings.append(NetworkFinding(
            "info", "IP WAN non vérifiée", "L'adresse WAN du routeur n'a pas été fournie.",
            "Compare-la manuellement à l'IP publique pour détecter CGNAT ou double NAT.",
        ))

    if proxy_listening is True:
        findings.append(NetworkFinding(
            "ok", "Proxy local joignable", "Le port du proxy accepte une connexion depuis ce PC.",
            "Cela ne vérifie pas le pare-feu externe ni la redirection NAT.",
        ))
    elif proxy_listening is False:
        findings.append(NetworkFinding(
            "warning", "Proxy local injoignable", "Aucun proxy n'accepte de connexion sur le port configuré.",
            "Démarre Caddy et vérifie que le port est libre.",
        ))

    findings.append(NetworkFinding(
        "info", "Accès Internet non testé", "Ce diagnostic ne teste pas les connexions depuis un réseau externe.",
        "Teste l'URL depuis un autre réseau, par exemple un téléphone en 4G/5G.",
    ))
    return findings