import os
from pathlib import Path

from web_deploy.core.dependencies import DependencyManager
from web_deploy.core.launcher import ServerLauncher
from web_deploy.core.health import wait_for_http, check_tcp_listener, http_question_response
from web_deploy.network.public_ip import get_public_ip
from web_deploy.proxy.local_proxy import LocalProxy
from web_deploy.core.diagnostics import log_known_error, log_firewall_advice
from web_deploy.core.port_manager import clear_port
from web_deploy.core.port_database import check_port, initialize_database


class Deployer:
    def __init__(self, config, log=print):
        self.config = config
        self.log = log
        self.launcher = None
        self.proxy = None

    def validate(self):
        path = self.config["server_file"]
        if not path:
            raise ValueError("Aucun fichier serveur n'a été sélectionné.")
        path = str(path).strip()
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Fichier serveur introuvable : {path}")

        host = str(self.config.get("host", "")).strip()
        try:
            port = int(self.config["port"])
            public_port = int(self.config["public_port"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Les ports serveur/public doivent être des nombres entiers.") from exc

        if not (1 <= port <= 65535 and 1 <= public_port <= 65535):
            raise ValueError("Les ports doivent être compris entre 1 et 65535.")

        initialize_database()
        public_info = check_port(public_port)
        if public_info and public_info["category"] == "browser_unsafe":
            raise ValueError(
                f"Le port public {public_port} est déconseillé/bloqué par certains navigateurs. "
                "Choisissez un port Web comme 5000, 5555, 8000, 8080, 8888 ou 9000."
            )
        if public_info and public_info["category"] == "router_reserved":
            self.log(
                f"[ATTENTION] Le port public {public_port} ({public_info['name']}) est souvent réservé par les équipements réseau. "
                "Son filtrage dépend du routeur ; préférez un port Web alternatif si possible."
            )

        if self.config.get("proxy_enabled", True) and public_port == port:
            raise ValueError(
                f"Le port serveur ({port}) et le port public ({public_port}) sont identiques. "
                "Ils doivent être différents : le serveur occupe le port interne et le proxy occupe le port public."
            )

        if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
            raise ValueError("Pour ce kit, l'adresse locale doit être 127.0.0.1, localhost ou 0.0.0.0.")

        return f"Serveur trouvé : {path} | {host}:{port} | accès : :{public_port}"

    def _project_root(self):
        # Le kit est prévu pour être lancé depuis la racine du projet.
        return Path(self.config.get("project_root") or os.getcwd()).resolve()

    def stop(self):
        """Arrête proprement le proxy et le serveur lancés par ce déployeur."""
        errors = []
        if self.proxy is not None:
            try:
                self.proxy.stop()
            except Exception as exc:
                errors.append(f"proxy: {exc}")
        if self.launcher is not None:
            try:
                self.launcher.stop()
            except Exception as exc:
                errors.append(f"serveur: {exc}")
        if errors:
            self.log("[ERREUR] Nettoyage incomplet : " + "; ".join(errors))
        else:
            self.log("[OK] Services arrêtés proprement.")

    def deploy(self):
        self.log("[INFO] Validation...")
        self.launcher = None
        self.proxy = None
        self.validate()

        python_executable = None
        if self.config.get("use_venv", True):
            self.log("[INFO] Préparation de l'environnement virtuel...")
            try:
                python_executable = DependencyManager(
                    self._project_root(),
                    self.log,
                    self.config.get("venv_name", ".venv"),
                ).prepare()
            except Exception as exc:
                self.log(f"[ERREUR] Préparation du venv : {exc}")
                log_known_error(self.log, exc, "dépendances / venv")
                raise

        server_port = int(self.config["port"])
        public_port = int(self.config["public_port"])
        self.log("[INFO] Nettoyage des ports sélectionnés avant le démarrage...")
        ports_to_clear = [(server_port, "serveur")]
        if self.config.get("proxy_enabled", True) and public_port != server_port:
            ports_to_clear.append((public_port, "proxy public"))
        for selected_port, label in ports_to_clear:
            if not clear_port(selected_port, self.log, label):
                exc = RuntimeError(f"Impossible de libérer le port {selected_port} ({label}).")
                log_known_error(self.log, exc, label)
                raise exc

        self.log(f"[INFO] Lancement du serveur Python sur {self.config['host']}:{server_port}...")
        self.launcher = ServerLauncher(
            self.config["server_file"],
            self.config["host"],
            server_port,
            self.log,
            python_executable=python_executable,
        )
        try:
            self.launcher.start()
        except Exception as exc:
            self.log(f"[ERREUR] Impossible de lancer le serveur Python : {exc}")
            log_known_error(self.log, exc, "serveur")
            raise

        if not wait_for_http(self.config["host"], server_port, timeout=12):
            exc = RuntimeError("Le serveur Python ne répond pas sur le port configuré.")
            self.log(f"[ERREUR] {exc}")
            log_known_error(self.log, ConnectionRefusedError("connection refused"), "vérification du serveur")
            raise exc

        ok, status, reason = http_question_response(self.config["host"], server_port)
        if ok:
            self.log(f"[OK] Test question/réponse HTTP : GET / -> {status} {reason}")
        else:
            self.log(f"[ERREUR] Test question/réponse HTTP sur {self.config['host']}:{server_port} : {reason}")
            log_known_error(self.log, ConnectionRefusedError(str(reason)), "question/réponse serveur")
            raise RuntimeError("Le serveur écoute mais ne répond pas correctement aux requêtes HTTP.")

        self.log(f"[OK] Serveur Python opérationnel sur {self.config['host']}:{server_port}.")

        if self.config.get("proxy_enabled", True):
            if public_port == server_port:
                exc = RuntimeError(
                    f"Le port public {public_port} est identique au port serveur {server_port}."
                )
                self.log("[ERREUR] Le proxy ne peut pas utiliser le même port que le serveur.")
                log_known_error(self.log, exc, "proxy public")
                raise exc

            # Le serveur vient d'être lancé : ne jamais nettoyer son port ici.
            # Seul le port public, distinct, peut être libéré juste avant le proxy.
            if not clear_port(public_port, self.log, "proxy public"):
                exc = RuntimeError(f"Impossible de libérer le port public {public_port}.")
                log_known_error(self.log, exc, "proxy public")
                raise exc

            self.log(f"[INFO] Démarrage du proxy public sur 0.0.0.0:{public_port} -> {self.config['host']}:{server_port}...")
            self.proxy = LocalProxy(
                "0.0.0.0",
                public_port,
                self.config["host"],
                server_port,
                self.log
            )
            try:
                self.proxy.start()
            except Exception as exc:
                self.log(f"[ERREUR] Impossible de démarrer le proxy : {exc}")
                log_known_error(self.log, exc, "proxy public")
                raise
            self.log(f"[OK] Proxy en écoute sur 0.0.0.0:{self.config['public_port']} -> {self.config['host']}:{self.config['port']}")

            # Vérification concrète : le port public accepte-t-il une connexion
            # depuis l'interface locale ? Cela sépare un problème du proxy/pare-feu
            # d'un problème de NAT ou d'accès Internet.
            local_ok, local_error = check_tcp_listener("127.0.0.1", public_port)
            if local_ok:
                self.log(f"[OK] Port public {public_port} : connexion TCP acceptée.")
                proxy_ok, proxy_status, proxy_reason = http_question_response("127.0.0.1", public_port)
                if proxy_ok:
                    self.log(f"[OK] Test question/réponse proxy : GET / -> {proxy_status} {proxy_reason}")
                else:
                    self.log(f"[ERREUR] Proxy {public_port} : TCP OK mais réponse HTTP absente : {proxy_reason}")
            else:
                self.log(f"[ERREUR] Port public {public_port} inaccessible localement : {local_error}")
                self.log("[SOLUTION] Vérifie le proxy et le pare-feu local.")

            self.log("[INFO] Si le test local est OK mais que l'IP publique ne répond pas, le blocage est probablement sur le routeur (NAT/port forwarding), le pare-feu en amont ou le fournisseur d'accès.")
            self.log(f"[INFO] Règle NAT attendue : TCP WAN {public_port} -> IP_LOCALE_DU_PC:{public_port}")
            self.log("[INFO] Pour un test fiable, utilise un appareil en 4G/5G ou un autre réseau : certains routeurs ne permettent pas le NAT loopback depuis le Wi-Fi local.")
            log_firewall_advice(self.log, public_port)

        try:
            ip = get_public_ip()
            if ip:
                self.log(f"[INFO] IP publique détectée : {ip}")
                self.log(
                    f"[INFO] Si ton routeur redirige le port {self.config['public_port']} "
                    f"vers cette machine, accès possible via : http://{ip}:{self.config['public_port']}"
                )
            else:
                self.log("[WARN] IP publique non détectée.")
        except Exception as exc:
            self.log(f"[WARN] Détection IP publique impossible : {exc}")

        self.log("[OK] Déploiement terminé.")
