"""Base SQLite locale des ports à éviter pour un accès Web public."""
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ports.db"

# Les ports de la catégorie browser_unsafe correspondent aux ports couramment
# refusés par les navigateurs Chromium/Firefox. La catégorie router_reserved
# regroupe des ports souvent réservés à des services, filtrés ou déconseillés
# par certaines box/routeurs. Ce n'est pas une interdiction universelle.
BROWSER_UNSAFE = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53,
    69, 77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115,
    117, 119, 123, 135, 139, 143, 179, 389, 427, 465, 512, 513, 514,
    515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587, 601, 636,
    989, 990, 993, 995, 2049, 3659, 4045, 4190, 6000, 6566,
    6665, 6666, 6667, 6668, 6669, 6697,
}

ROUTER_RESERVED = {
    67: "DHCP serveur",
    68: "DHCP client",
    161: "SNMP",
    162: "SNMP traps",
    1900: "UPnP / SSDP",
    5353: "mDNS / Bonjour",
    5355: "LLMNR",
}

RECOMMENDED = {
    5000: "port Web alternatif courant",
    5555: "port Web alternatif courant",
    8000: "port Web alternatif courant",
    8080: "port Web alternatif courant",
    8888: "port Web alternatif courant",
    9000: "port Web alternatif courant",
}


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def initialize_database():
    with _connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ports (
                port INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                severity TEXT NOT NULL,
                note TEXT NOT NULL
            )
        """)
        for port in sorted(BROWSER_UNSAFE):
            con.execute(
                "INSERT OR IGNORE INTO ports VALUES (?, ?, ?, ?, ?)",
                (port, "browser_unsafe", "Port refusé/déconseillé par les navigateurs", "bloquant",
                 "Éviter pour une URL Web : certains navigateurs refusent directement la connexion."),
            )
        for port, name in ROUTER_RESERVED.items():
            con.execute(
                "INSERT OR IGNORE INTO ports VALUES (?, ?, ?, ?, ?)",
                (port, "router_reserved", name, "attention",
                 "Port généralement réservé à un service réseau ; le filtrage dépend du routeur et du réseau."),
            )
        for port, note in RECOMMENDED.items():
            con.execute(
                "INSERT OR IGNORE INTO ports VALUES (?, ?, ?, ?, ?)",
                (port, "recommended", "Port adapté à un service Web", "ok", note),
            )


def check_port(port):
    """Retourne les infos de la base pour un port, ou None."""
    initialize_database()
    with _connect() as con:
        row = con.execute(
            "SELECT port, category, name, severity, note FROM ports WHERE port = ?",
            (int(port),),
        ).fetchone()
    if not row:
        return None
    return {
        "port": row[0], "category": row[1], "name": row[2],
        "severity": row[3], "note": row[4],
    }
