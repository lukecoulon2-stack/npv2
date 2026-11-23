import os
import threading
from datetime import datetime
from pathlib import Path

from web_deploy.core.dependencies import DependencyManager
from web_deploy.core.launcher import ServerLauncher
from web_deploy.core.health import wait_for_http, check_tcp_listener, http_question_response
from web_deploy.network.public_ip import get_public_ip
from web_deploy.proxy.caddy_gateway import CaddyGateway
from web_deploy.core.diagnostics import log_known_error, log_firewall_advice
from web_deploy.core.port_manager import clear_port, find_port_pids
from web_deploy.core.port_database import check_port, initialize_database
from web_deploy.security.access_control import AccessPolicy
from web_deploy.network.tunnel_manager import TunnelManager


class Deployer:
    def __init__(self, config, log=print):
        self.config = config
        self.log = log
        self.launcher = None
        self.proxy = None
        self.tunnel = None
        self.public_url = None
        self.access_policy = None
        self._monitor_stop = threading.Event()
        self._monitor_thread = None
        self._last_health_check = None
        self._last_health_result = "non vérifié"

    def status_snapshot(self):
        process = self.launcher.process if self.launcher else None
        if process is None:
            server_status = "arrêté"
        elif process.poll() is None:
            server_status = "actif"
        else:
            server_status = "arrêté"

        if self.proxy is None:
            if self.config.get("direct_access_enabled", False):
                proxy_status = "accès direct sans proxy"
            else:
                proxy_status = "coupé" if self.config.get("proxy_enabled", True) else "désactivé"
        else:
            proxy_process = getattr(self.proxy, "process", None)
            if proxy_process is None:
                proxy_status = "démarrage"
            else:
                proxy_status = "actif" if proxy_process.poll() is None else "arrêté"

        return {
            "server": server_status,
            "proxy": proxy_status,
            "https": bool(self.config.get("https_enabled")) and proxy_status == "actif",
            "tunnel": bool(self.tunnel and self.tunnel.process and self.tunnel.process.poll() is None),
            "public_url": self.public_url,
            "last_health_check": self._last_health_check,
            "last_health_result": self._last_health_result,
        }

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

        direct_access_enabled = bool(self.config.get("direct_access_enabled", False))
        proxy_enabled = bool(self.config.get("proxy_enabled", True))
        if direct_access_enabled and proxy_enabled:
            raise ValueError("Choisis soit le proxy Caddy, soit l'accès direct sans proxy.")
        if direct_access_enabled:
            host = "0.0.0.0"
            self.config["host"] = host

        try:
            self.config["health_path"] = CaddyGateway.validate_health_path(
                self.config.get("health_path", "/")
            )
            health_status = int(self.config.get("health_expected_status", 200))
            if not 200 <= health_status <= 599:
                raise ValueError("Le code de santé HTTP doit être compris entre 200 et 599.")
            self.config["health_expected_status"] = health_status
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configuration health check invalide : {exc}") from exc

        https_enabled = bool(self.config.get("https_enabled", False))
        tunnel_enabled = bool(self.config.get("tunnel_enabled", False))
        auth_enabled = bool(self.config.get("auth_enabled", False))
        if direct_access_enabled and (https_enabled or tunnel_enabled or auth_enabled):
            raise ValueError("HTTPS, le tunnel et l'authentification Basic exigent le proxy Caddy.")
        if tunnel_enabled and not self.config.get("proxy_enabled", True):
            raise ValueError("Le tunnel Cloudflare exige l'activation du proxy Caddy.")
        if tunnel_enabled and https_enabled:
            raise ValueError("Désactive HTTPS Caddy avec le tunnel ; Cloudflare fournit le HTTPS public.")
        if https_enabled:
            if not self.config.get("proxy_enabled", True):
                raise ValueError("HTTPS exige l'activation du proxy public.")
            if public_port != 443:
                raise ValueError("En mode HTTPS, le port public doit être 443.")
            if port in (80, 443):
                raise ValueError("En mode HTTPS, le port serveur doit être différent de 80 et 443.")
            self.config["https_domain"] = CaddyGateway.validate_domain(
                self.config.get("https_domain", "")
            )
            for tls_port in (80, 443):
                pids = find_port_pids(tls_port)
                if pids:
                    raise ValueError(
                        f"Le port TLS {tls_port} est déjà utilisé par le(s) PID "
                        f"{', '.join(map(str, pids))}. Aucun processus n'a été arrêté."
                    )
        elif auth_enabled and not tunnel_enabled:
            raise ValueError("L'authentification Basic exige HTTPS ou le tunnel HTTPS Cloudflare.")

        if self.config.get("proxy_enabled", True):
            gateway = CaddyGateway(
                self.config.get("https_domain") if https_enabled else None,
                host,
                port,
                listen_port=443 if https_enabled else public_port,
                https=https_enabled,
                listen_host="127.0.0.1" if tunnel_enabled else "0.0.0.0",
                health_path=self.config.get("health_path", "/"),
                health_status=self.config.get("health_expected_status", 200),
                health_interval=self.config.get("health_check_interval", 10),
                health_timeout=self.config.get("health_check_timeout", 3),
            )
            if not gateway.executable:
                raise ValueError(
                    "Caddy v2 est requis comme proxy. Installe Caddy ou définis WEB_DEPLOY_CADDY."
                )
            try:
                gateway.verify_binary()
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc

        if tunnel_enabled:
            try:
                TunnelManager(self.log).verify_binary()
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc

        auth_credentials = self.config.get("auth_credentials")
        if auth_enabled and not auth_credentials:
            raise ValueError("Saisis un identifiant et un mot de passe avant le déploiement.")

        ip_allowlist_enabled = proxy_enabled and bool(
            self.config.get(
                "ip_allowlist_enabled",
                bool(self.config.get("allowed_ip_ranges")),
            )
        )
        allowed_ip_ranges = self.config.get("allowed_ip_ranges", [])
        if ip_allowlist_enabled and not allowed_ip_ranges:
            raise ValueError("Ajoute au moins une adresse ou plage CIDR à la liste blanche.")
        rate_limit_enabled = proxy_enabled and bool(self.config.get("rate_limit_enabled", True))
        daily_upload_limit_bytes = None
        if proxy_enabled and self.config.get("daily_upload_limit_enabled", False):
            try:
                daily_upload_limit_bytes = int(self.config.get("daily_upload_limit_mib", 1024)) * 1024 * 1024
            except (TypeError, ValueError) as exc:
                raise ValueError("Le quota quotidien doit être un nombre de MiB.") from exc

        try:
            self.access_policy = AccessPolicy(
                allowed_ip_ranges=allowed_ip_ranges if ip_allowlist_enabled else [],
                max_requests=self.config.get("rate_limit_requests", 120) if rate_limit_enabled else 0,
                window_seconds=self.config.get("rate_limit_window_seconds", 60),
                auth_credentials=auth_credentials if auth_enabled else None,
                daily_upload_limit_bytes=daily_upload_limit_bytes,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configuration de sécurité invalide : {exc}") from exc

        return f"Serveur trouvé : {path} | {host}:{port} | accès : :{public_port}"

    def _project_root(self):
        # Le kit est prévu pour être lancé depuis la racine du projet.
        return Path(self.config.get("project_root") or os.getcwd()).resolve()

    def _health_host(self):
        return "127.0.0.1" if self.config.get("host") == "0.0.0.0" else self.config["host"]

    def stop(self, force=False):
        """Arrête proprement le proxy et le serveur lancés par ce déployeur."""
        errors = []
        self._monitor_stop.set()
        monitor_thread = self._monitor_thread
        if monitor_thread is threading.current_thread():
            self._monitor_thread = None
        elif monitor_thread is not None:
            monitor_thread.join(timeout=11)
            if monitor_thread.is_alive():
                errors.append("supervision: thread toujours actif après le délai d'arrêt")
            else:
                self._monitor_thread = None
        if self.tunnel is not None:
            try:
                self.tunnel.stop(force=force)
                self.tunnel = None
                self.public_url = None
            except Exception as exc:
                errors.append(f"tunnel: {exc}")
        if self.proxy is not None:
            try:
                self.proxy.stop(force=force)
            except Exception as exc:
                errors.append(f"proxy: {exc}")
        if self.launcher is not None:
            try:
                self.launcher.stop(force=force)
            except Exception as exc:
                errors.append(f"serveur: {exc}")
        if errors:
            self.log("[ERREUR] Nettoyage incomplet : " + "; ".join(errors))
            return False
        self.access_policy = None
        self.config.pop("auth_credentials", None)
        self.log("[OK] Services arrêtés proprement.")
        return True

    def stop_public_access(self):
        if self.proxy is None:
            self.log("[INFO] L'accès public est déjà coupé.")
            return True
        if self.tunnel is not None:
            try:
                self.tunnel.stop()
                self.tunnel = None
                self.public_url = None
            except Exception as exc:
                self.log(f"[ERREUR] Impossible d'arrêter le tunnel : {exc}")
                return False
        try:
            self.proxy.stop()
        except Exception as exc:
            self.log(f"[ERREUR] Impossible de couper l'accès public : {exc}")
            return False
        self.proxy = None
        self.log("[OK] Accès public coupé ; le serveur local continue de fonctionner.")
        return True

    def start_public_access(self):
        if not self.config.get("proxy_enabled", True):
            raise RuntimeError("Le proxy public est désactivé dans la configuration.")
        process = self.launcher.process if self.launcher else None
        if process is None or process.poll() is not None:
            raise RuntimeError("Le serveur local n'est pas actif.")
        if self.proxy is not None:
            self.log("[INFO] L'accès public est déjà actif.")
            return

        public_port = int(self.config["public_port"])
        https_enabled = bool(self.config.get("https_enabled"))
        tunnel_enabled = bool(self.config.get("tunnel_enabled"))
        if https_enabled:
            for tls_port in (80, 443):
                pids = find_port_pids(tls_port)
                if pids:
                    raise RuntimeError(
                        f"Le port TLS {tls_port} est déjà utilisé par le(s) PID "
                        f"{', '.join(map(str, pids))}. Aucun processus n'a été arrêté."
                    )
        elif not clear_port(public_port, self.log, "proxy public"):
            raise RuntimeError(f"Impossible d'ouvrir le port public {public_port}.")

        proxy = CaddyGateway(
            self.config.get("https_domain") if https_enabled else None,
            self.config["host"],
            int(self.config["port"]),
            self.log,
            access_policy=self.access_policy,
            listen_port=443 if https_enabled else public_port,
            https=https_enabled,
            auth_enabled=bool(self.config.get("auth_enabled")),
            health_path=self.config.get("health_path", "/"),
            health_status=self.config.get("health_expected_status", 200),
            health_interval=self.config.get("health_check_interval", 10),
            health_timeout=self.config.get("health_check_timeout", 3),
            listen_host="127.0.0.1" if tunnel_enabled else "0.0.0.0",
        )
        self.proxy = proxy
        try:
            proxy.start()
            if tunnel_enabled:
                self.tunnel = TunnelManager(self.log)
                self.public_url = self.tunnel.start(public_port)
                self.log(f"[OK] Tunnel public actif : {self.public_url}")
            elif self.config.get("https_enabled"):
                ok, error = check_tcp_listener("127.0.0.1", 443, timeout=4)
                if not ok:
                    raise RuntimeError(f"Le port HTTPS local ne répond pas : {error}")
            else:
                ok, _status, reason = http_question_response(
                    "127.0.0.1", public_port, timeout=4
                )
                if not ok:
                    raise RuntimeError(f"Le proxy public ne répond pas en HTTP : {reason}")
        except Exception:
            if self.tunnel is not None:
                try:
                    self.tunnel.stop(force=True)
                except Exception as cleanup_error:
                    self.log(f"[ERREUR] Arrêt tunnel incomplet : {cleanup_error}")
                self.tunnel = None
                self.public_url = None
            proxy.stop()
            self.proxy = None
            raise
        self.log(f"[OK] Accès public rétabli sur 0.0.0.0:{public_port}.")

    def _monitor_services(self):
        interval = max(0.1, float(self.config.get("health_check_interval", 10)))
        timeout = min(10.0, max(0.5, float(self.config.get("health_check_timeout", 3))))
        health_path = self.config.get("health_path", "/")
        expected_status = int(self.config.get("health_expected_status", 200))
        max_restarts = max(0, int(self.config.get("max_restart_attempts", 3)))
        restart_enabled = bool(self.config.get("auto_restart", False))
        restart_attempts = 0
        consecutive_failures = 0

        while not self._monitor_stop.wait(interval):
            self._last_health_check = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            process = self.launcher.process if self.launcher else None
            if process is None or process.poll() is not None:
                healthy = False
                reason = "Le processus serveur s'est arrêté."
            else:
                healthy, _status, reason = http_question_response(
                    self._health_host(),
                    int(self.config["port"]),
                    path=health_path,
                    timeout=timeout,
                    expected_status=expected_status,
                )

            proxy = self.proxy
            if healthy and proxy is not None:
                if self.config.get("https_enabled"):
                    proxy_healthy, _status, reason = http_question_response(
                        "127.0.0.1",
                        443,
                        path=health_path,
                        timeout=timeout,
                        https=True,
                        server_hostname=self.config["https_domain"],
                    )
                else:
                    proxy_healthy, _status, reason = http_question_response(
                        "127.0.0.1",
                        int(self.config["public_port"]),
                        path=health_path,
                        timeout=timeout,
                    )
                if not proxy_healthy:
                    if self.proxy is not proxy:
                        continue
                    self.log(f"[ERREUR] Vérification du proxy échouée : {reason}")
                    self.stop()
                    return

            if healthy:
                self._last_health_result = "OK"
                consecutive_failures = 0
                continue

            self._last_health_result = f"Échec : {reason}"
            consecutive_failures += 1
            self.log(
                f"[ATTENTION] Health check serveur échoué "
                f"({consecutive_failures}/2) : {reason}"
            )
            if consecutive_failures < 2:
                continue

            if restart_enabled and restart_attempts < max_restarts:
                restart_attempts += 1
                self.log(
                    f"[INFO] Redémarrage automatique du serveur "
                    f"({restart_attempts}/{max_restarts})..."
                )
                try:
                    self.launcher.stop()
                    self.launcher.start()
                    restarted, _status, reason = http_question_response(
                        self._health_host(),
                        int(self.config["port"]),
                        path=health_path,
                        timeout=timeout,
                        expected_status=expected_status,
                    )
                    if restarted:
                        self.log("[OK] Serveur rétabli après redémarrage.")
                        consecutive_failures = 0
                        continue
                    self.log(f"[ERREUR] Le serveur redémarré ne répond pas en HTTP : {reason}")
                except Exception as exc:
                    self.log(f"[ERREUR] Redémarrage du serveur impossible : {exc}")

            self.log("[ERREUR] Le service ne répond plus ; arrêt de l'accès public.")
            self.stop()
            return

    def _start_monitor(self):
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_services,
            name="web-deployer-health-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def deploy(self):
        self.log("[INFO] Validation...")
        self.launcher = None
        self.proxy = None
        self.tunnel = None
        self.public_url = None
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
        if (
            self.config.get("proxy_enabled", True)
            and not self.config.get("https_enabled")
            and public_port != server_port
        ):
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
            module=self.config.get("server_module"),
            arguments=self.config.get("server_args", ()),
            working_directory=self._project_root(),
        )
        try:
            self.launcher.start()
        except Exception as exc:
            self.log(f"[ERREUR] Impossible de lancer le serveur Python : {exc}")
            log_known_error(self.log, exc, "serveur")
            raise

        health_host = self._health_host()
        if not wait_for_http(health_host, server_port, timeout=12):
            exc = RuntimeError("Le serveur Python ne répond pas sur le port configuré.")
            self.log(f"[ERREUR] {exc}")
            log_known_error(self.log, ConnectionRefusedError("connection refused"), "vérification du serveur")
            raise exc

        health_path = self.config.get("health_path", "/")
        expected_status = int(self.config.get("health_expected_status", 200))
        health_timeout = min(10.0, max(0.5, float(self.config.get("health_check_timeout", 3))))
        ok, status, reason = http_question_response(
            health_host,
            server_port,
            path=health_path,
            timeout=health_timeout,
            expected_status=expected_status,
        )
        if ok:
            self._last_health_check = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            self._last_health_result = f"OK : {status} {reason}"
            self.log(f"[OK] Health check serveur : GET {health_path} -> {status} {reason}")
        else:
            self._last_health_check = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            self._last_health_result = f"Échec : {reason}"
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

            if self.config.get("https_enabled"):
                self.log(
                    f"[INFO] Démarrage HTTPS automatique pour {self.config['https_domain']} "
                    "sur les ports 80/443..."
                )
            else:
                # Le serveur vient d'être lancé : ne jamais nettoyer son port ici.
                if not clear_port(public_port, self.log, "proxy public"):
                    exc = RuntimeError(f"Impossible de libérer le port public {public_port}.")
                    log_known_error(self.log, exc, "proxy public")
                    raise exc
                self.log(f"[INFO] Démarrage du proxy public sur 0.0.0.0:{public_port} -> {self.config['host']}:{server_port}...")
            self.proxy = CaddyGateway(
                self.config.get("https_domain") if self.config.get("https_enabled") else None,
                self.config["host"],
                server_port,
                self.log,
                access_policy=self.access_policy,
                listen_port=443 if self.config.get("https_enabled") else public_port,
                https=bool(self.config.get("https_enabled")),
                auth_enabled=bool(self.config.get("auth_enabled")),
                health_path=self.config.get("health_path", "/"),
                health_status=self.config.get("health_expected_status", 200),
                listen_host=(
                    "127.0.0.1"
                    if self.config.get("tunnel_enabled")
                    else "0.0.0.0"
                ),
            )
            try:
                self.proxy.start()
                if self.config.get("tunnel_enabled"):
                    self.tunnel = TunnelManager(self.log)
                    self.public_url = self.tunnel.start(public_port)
                    self.log(f"[OK] Tunnel public actif : {self.public_url}")
            except Exception as exc:
                if self.tunnel is not None:
                    try:
                        self.tunnel.stop(force=True)
                    except Exception as cleanup_error:
                        self.log(f"[ERREUR] Arrêt tunnel incomplet : {cleanup_error}")
                    self.tunnel = None
                    self.public_url = None
                self.proxy.stop(force=True)
                self.proxy = None
                self.log(f"[ERREUR] Impossible de démarrer le proxy : {exc}")
                log_known_error(self.log, exc, "proxy public")
                raise
            if self.config.get("https_enabled"):
                self.log(
                    f"[OK] HTTPS actif : https://{self.config['https_domain']} "
                    f"-> {self.config['host']}:{self.config['port']}"
                )
            else:
                self.log(f"[OK] Proxy en écoute sur 0.0.0.0:{self.config['public_port']} -> {self.config['host']}:{self.config['port']}")

            # Vérification concrète : le port public accepte-t-il une connexion
            # depuis l'interface locale ? Cela sépare un problème du proxy/pare-feu
            # d'un problème de NAT ou d'accès Internet.
            caddy_port = 443 if self.config.get("https_enabled") else public_port
            local_ok, local_error = check_tcp_listener("127.0.0.1", caddy_port)
            if local_ok:
                self.log(f"[OK] Port public {caddy_port} : connexion TCP acceptée.")
                if not self.config.get("https_enabled"):
                    proxy_ok, proxy_status, proxy_reason = http_question_response("127.0.0.1", public_port)
                    if proxy_ok:
                        self.log(f"[OK] Test question/réponse proxy : GET / -> {proxy_status} {proxy_reason}")
                    else:
                        self.log(f"[ERREUR] Proxy {public_port} : TCP OK mais réponse HTTP absente : {proxy_reason}")
            else:
                self.log(f"[ERREUR] Port public {public_port} inaccessible localement : {local_error}")
                self.log("[SOLUTION] Vérifie le proxy et le pare-feu local.")

            if self.config.get("tunnel_enabled"):
                self.log(f"[INFO] Aucun port NAT à ouvrir ; l'URL est fournie par le tunnel : {self.public_url}")
            else:
                self.log("[INFO] Si le test local est OK mais que l'IP publique ne répond pas, le blocage est probablement sur le routeur (NAT/port forwarding), le pare-feu en amont ou le fournisseur d'accès.")
                self.log(f"[INFO] Règle NAT attendue : TCP WAN {public_port} -> IP_LOCALE_DU_PC:{public_port}")
                self.log("[INFO] Pour un test fiable, utilise un appareil en 4G/5G ou un autre réseau : certains routeurs ne permettent pas le NAT loopback depuis le Wi-Fi local.")
                log_firewall_advice(self.log, public_port)
                if self.config.get("https_enabled"):
                    log_firewall_advice(self.log, 80)
        elif self.config.get("direct_access_enabled", False):
            self.log(f"[INFO] Accès direct sans proxy sur 0.0.0.0:{server_port} (HTTP non chiffré).")
            self.log(f"[INFO] Règle NAT attendue : TCP WAN {public_port} -> IP_LOCALE_DU_PC:{server_port}")
            self.log("[ATTENTION] Les protections réseau de Caddy ne s'appliquent pas en accès direct.")
            log_firewall_advice(self.log, server_port)

        self._start_monitor()

        try:
            if self.public_url:
                self.log(f"[INFO] URL publique du tunnel : {self.public_url}")
            else:
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
