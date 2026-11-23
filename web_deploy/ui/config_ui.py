import json
import os
import shlex
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from web_deploy.core.deployer import Deployer
from web_deploy.core.logging_config import get_file_logger
from web_deploy.core.port_database import check_port, initialize_database
from web_deploy.core.server_detector import detect_server
from web_deploy.core.health import check_tcp_listener
from web_deploy.network.diagnostics import diagnose_network, resolve_domain

CONFIG_FILE = "web_deploy_config.json"


class ConfigUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Web Deployer")
        self.root.geometry("900x760")
        self.root.minsize(860, 680)
        self._apply_theme()

        self.server_file = tk.StringVar()
        self.module_name = tk.StringVar(value="app")
        self.server_module = tk.StringVar(value="")
        self.server_args = tk.StringVar(value="")
        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.IntVar(value=5555)
        self.public_port = tk.IntVar(value=8000)
        self.auto_start = tk.BooleanVar(value=True)
        self.auto_restart = tk.BooleanVar(value=False)
        self.max_restart_attempts = tk.IntVar(value=3)
        self.health_check_interval = tk.IntVar(value=10)
        self.health_check_timeout = tk.IntVar(value=3)
        self.health_path = tk.StringVar(value="/")
        self.health_expected_status = tk.IntVar(value=200)
        self.allowed_ip_ranges = tk.StringVar(value="")
        self.ip_allowlist_enabled = tk.BooleanVar(value=False)
        self.rate_limit_requests = tk.IntVar(value=120)
        self.rate_limit_enabled = tk.BooleanVar(value=True)
        self.daily_upload_limit_enabled = tk.BooleanVar(value=False)
        self.daily_upload_limit_mib = tk.IntVar(value=1024)
        self.https_enabled = tk.BooleanVar(value=False)
        self.https_domain = tk.StringVar(value="")
        self.tunnel_enabled = tk.BooleanVar(value=False)
        self.router_wan_ip = tk.StringVar(value="")
        self.auth_enabled = tk.BooleanVar(value=False)
        self._auth_credentials = None
        self.proxy_enabled = tk.BooleanVar(value=True)
        self.direct_access_enabled = tk.BooleanVar(value=False)
        self.use_venv = tk.BooleanVar(value=True)
        self.show_classic_logs = tk.BooleanVar(value=False)

        self.status = tk.StringVar(value="Prêt.")
        self.dashboard_state = tk.StringVar(value="Serveur : arrêté | Accès public : coupé")
        self.public_ip = tk.StringVar(value="IP publique : détection...")
        self.public_url = tk.StringVar(value="http://...:8080")
        self.deployer = None
        self._deployment_in_progress = False
        self._services_active = False
        self._public_access_operation = False
        self._closing = False
        self.file_logger = get_file_logger()
        self._public_ip_value = None
        self._panel_windows = {}
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        initialize_database()
        self._show_tutorial()

    def _apply_theme(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TLabel", font=("TkDefaultFont", 10))
        style.configure("TFrame", padding=0)
        style.configure("TLabelframe", padding=10)
        style.configure("TLabelframe.Label", font=("TkDefaultFont", 10, "bold"))
        style.configure("TEntry", padding=(6, 4))
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", padding=(12, 8))

        self.root.option_add("*Font", ("TkDefaultFont", 10))
        self.root.option_add("*Entry.Font", ("TkDefaultFont", 10))
        self.root.option_add("*Label.Font", ("TkDefaultFont", 10))
        self.root.option_add("*Button.Font", ("TkDefaultFont", 10, "bold"))

    def _clear(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def _show_tutorial(self):
        self._clear()

        main = ttk.Frame(self.root, padding=18)
        main.pack(fill="both", expand=True)

        ttk.Label(
            main, text="WEB DEPLOYER — GUIDE",
            font=("TkDefaultFont", 18, "bold")
        ).pack(anchor="w")

        ttk.Label(
            main,
            text="Avant de déployer, prépare la redirection de port sur ton routeur.",
            wraplength=650
        ).pack(anchor="w", pady=(4, 14))

        guide = ttk.LabelFrame(main, text="Configuration du routeur", padding=14)
        guide.pack(fill="both", expand=True)

        local_ip = self._get_local_ip()

        lines = [
            ("1.", "Ouvre la page d'administration de ton routeur / ta box."),
            ("2.", "Cherche la rubrique NAT, Redirection de ports, Port Forwarding ou Serveur virtuel."),
            ("3.", "Crée une règle TCP qui redirige un port public vers le PC qui héberge ton projet."),
            ("4.", f"Adresse IP interne à utiliser : {local_ip}"),
            ("5.", "Port interne : utilise le même port que celui configuré dans Web Deployer, par défaut 5555."),
            ("6.", "Port externe : choisis le port que les visiteurs utiliseront, par défaut 8000."),
            ("7.", "Enregistre la règle et, si possible, réserve cette adresse IP dans le DHCP du routeur."),
        ]

        for num, desc in lines:
            row = ttk.Frame(guide)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=num, width=4, font=("TkDefaultFont", 10, "bold")).pack(side="left", anchor="n")
            ttk.Label(row, text=desc, wraplength=590, justify="left").pack(side="left", fill="x", expand=True)

        example = ttk.LabelFrame(main, text="Exemple de règle", padding=12)
        example.pack(fill="x", pady=12)

        example_text = (
            f"IP interne : {local_ip}\n"
            "Protocole   : TCP\n"
            "Port externe: 8000\n"
            "Port interne: 5555"
        )
        ttk.Label(example, text=example_text, justify="left", font=("TkFixedFont", 10)).pack(anchor="w")

        warning = ttk.Label(
            main,
            text="Attention : ouvrir un port rend un service accessible depuis Internet. "
                 "N'expose que le service prévu et utilise HTTPS/authentification pour un vrai site public.",
            wraplength=650,
            justify="left"
        )
        warning.pack(fill="x", pady=(4, 12))

        ttk.Button(
            main,
            text="J'AI COMPRIS — CONTINUER",
            command=self._show_config
        ).pack(anchor="e")

    def _get_local_ip(self):
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("192.0.2.1", 80))
            ip = sock.getsockname()[0]
            sock.close()
            return ip
        except OSError:
            return "IP locale non détectée"

    def _show_config(self):
        self._show_network_tutorial()

    def _show_network_tutorial(self):
        self._clear()

        # Mise en page fixe : le bouton d'action reste toujours visible.
        main = ttk.Frame(self.root, padding=(14, 12))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        ttk.Label(
            main, text="WEB DEPLOYER — ACCÈS PUBLIC",
            font=("TkDefaultFont", 17, "bold")
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            main,
            text="Vérifie le PC, le routeur et l'accès Internet avant de lancer le site.",
            wraplength=700, justify="left"
        ).grid(row=1, column=0, sticky="ew", pady=(4, 8))

        # Zone centrale défilante : son contenu ne peut plus pousser le bouton hors écran.
        content_frame = ttk.Frame(main)
        content_frame.grid(row=2, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(content_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        body = ttk.Frame(canvas, padding=(2, 2, 8, 8))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.columnconfigure(0, weight=1)

        def update_scroll(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_body(event):
            canvas.itemconfigure(window_id, width=event.width)

        body.bind("<Configure>", update_scroll)
        canvas.bind("<Configure>", resize_body)

        local_ip = self._get_local_ip()
        public_port = self.public_port.get()

        firewall = ttk.LabelFrame(body, text="1 — Autoriser le port public sur le PC", padding=10)
        firewall.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            firewall,
            text=(
                "Windows (PowerShell administrateur) :\n"
                f"New-NetFirewallRule -DisplayName \"Web Deployer {public_port}\" -Direction Inbound -Protocol TCP -LocalPort {public_port} -Action Allow\n\n"
                "Linux / UFW :  sudo ufw allow PORT/tcp\n"
                "Linux / firewalld :  sudo firewall-cmd --permanent --add-port=PORT/tcp puis sudo firewall-cmd --reload"
            ),
            justify="left", wraplength=650, font=("TkFixedFont", 9)
        ).pack(anchor="w", fill="x")

        router = ttk.LabelFrame(body, text="2 — Configurer le routeur / la box", padding=10)
        router.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            router,
            text=(
                f"PC cible : {local_ip}\n"
                "Protocole : TCP\n"
                f"Port WAN/public : {public_port}\n"
                f"Port destination PC : {public_port}\n\n"
                "Dans NAT / Port Forwarding, redirige le port public vers cette IP. "
                "Réserve cette IP dans le DHCP si possible."
            ),
            justify="left", wraplength=650
        ).pack(anchor="w", fill="x")

        test = ttk.LabelFrame(body, text="3 — Tester depuis Internet", padding=10)
        test.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            test,
            text=(
                "Utilise l'adresse publique affichée par Web Deployer :\n"
                f"http://IP_PUBLIQUE:{public_port}\n\n"
                "Teste idéalement depuis un téléphone en 4G/5G. Si 127.0.0.1 fonctionne "
                "mais pas l'adresse publique, vérifie le pare-feu, le NAT, le port et le CGNAT. "
                "Un test depuis le même Wi-Fi peut aussi être trompeur si le routeur ne supporte pas le NAT loopback."
            ),
            justify="left", wraplength=650
        ).pack(anchor="w", fill="x")

        warning = ttk.Label(
            body,
            text="Conseil sécurité : n'ouvre que le port nécessaire et n'expose pas une application de test non sécurisée sur Internet.",
            wraplength=650, justify="left"
        )
        warning.grid(row=3, column=0, sticky="ew", pady=(0, 6))

        # Barre fixe hors zone défilante : toujours visible.
        action_bar = ttk.Frame(main, padding=(0, 8, 0, 0))
        action_bar.grid(row=3, column=0, sticky="ew")
        action_bar.columnconfigure(0, weight=1)
        ttk.Button(
            action_bar,
            text="J'AI COMPRIS — OUVRIR LA CONFIGURATION",
            command=self._show_config_after_tutorial
        ).grid(row=0, column=1, sticky="e")

    def _show_config_after_tutorial(self):
        self._clear()
        self._build()
        self._load_config()
        threading.Thread(target=self._refresh_public_ip, daemon=True).start()
        self._refresh_dashboard()

    def _build(self):
        main = ttk.Frame(self.root, padding=(18, 14))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # En-tête compact : le lien public reste toujours visible.
        header = ttk.Frame(main, padding=(0, 0, 0, 10))
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="WEB DEPLOYER", font=("TkDefaultFont", 18, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.public_ip, font=("TkDefaultFont", 10, "bold")).pack(side="right", padx=(10, 0))

        public_box = ttk.Frame(main, relief="groove", padding=(12, 9))
        public_box.pack(fill="x", pady=(0, 9))
        ttk.Label(public_box, text="ACCÈS PUBLIC", font=("TkDefaultFont", 9, "bold")).pack(side="left")
        link = ttk.Label(
            public_box, textvariable=self.public_url, cursor="hand2",
            font=("TkDefaultFont", 11, "underline")
        )
        link.pack(side="left", padx=(14, 0))
        link.bind("<Button-1>", self._open_public_url)
        ttk.Label(
            public_box,
            text="(redirection NAT requise)",
            foreground="#666666"
        ).pack(side="right")

        dashboard = ttk.Frame(main, padding=(2, 0, 2, 10))
        dashboard.pack(fill="x")
        ttk.Label(
            dashboard,
            textvariable=self.dashboard_state,
            font=("TkDefaultFont", 10, "bold"),
            anchor="w",
        ).pack(fill="x")

        form = self._collapsible_section(main, "Application", expanded=True)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=0)

        ttk.Label(form, text="Fichier du serveur :").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.server_file).grid(row=0, column=1, sticky="ew", padx=7)
        ttk.Button(form, text="Parcourir…", command=self._browse).grid(row=0, column=2, padx=(2, 0))
        ttk.Button(form, text="Détecter", command=self._detect_server).grid(row=0, column=3, padx=(4, 0))

        ttk.Label(form, text="Objet / module :").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.module_name).grid(row=1, column=1, sticky="ew", padx=7)
        ttk.Label(form, text="Optionnel").grid(row=1, column=2, sticky="w")

        ttk.Label(form, text="Adresse locale :").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.host).grid(row=2, column=1, sticky="ew", padx=7)

        ttk.Label(form, text="Port serveur :").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Spinbox(form, from_=1024, to=65535, textvariable=self.port, width=9).grid(row=3, column=1, sticky="w", padx=7)

        ttk.Label(form, text="Port public :").grid(row=3, column=2, sticky="e", padx=(8, 4))
        public_spin = ttk.Spinbox(form, from_=1024, to=65535, textvariable=self.public_port, width=9)
        public_spin.grid(row=3, column=3, sticky="w")
        self.public_port.trace_add("write", lambda *_: self._update_public_url())
        ttk.Button(form, text="Vérifier le port", command=self._check_public_port).grid(row=4, column=3, sticky="w", pady=(5, 0))
        ttk.Label(form, text="Arguments serveur :").grid(row=4, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(form, textvariable=self.server_args).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=7, pady=(5, 0)
        )

        options = self._collapsible_section(main, "Options", expanded=True)
        options.pack(fill="x", pady=8)
        options.columnconfigure(1, weight=1)
        for idx in range(0, 5):
            options.columnconfigure(idx, weight=0)
        self.proxy_access_check = ttk.Checkbutton(
            options, text="Proxy public (Caddy)", variable=self.proxy_enabled,
            command=self._select_proxy_access,
        )
        self.proxy_access_check.grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.direct_access_check = ttk.Checkbutton(
            options,
            text="Accès direct sans Caddy",
            variable=self.direct_access_enabled,
            command=self._select_direct_access,
        )
        self.direct_access_check.grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Checkbutton(options, text="Venv + dépendances", variable=self.use_venv).grid(row=0, column=2, sticky="w", padx=(0, 14))
        ttk.Checkbutton(options, text="Démarrage automatique", variable=self.auto_start).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(options, text="Redémarrage auto.", variable=self.auto_restart).grid(row=1, column=0, sticky="w", padx=(0, 14))
        ttk.Label(options, text="Tentatives max. :").grid(row=1, column=1, sticky="e")
        ttk.Spinbox(
            options, from_=0, to=10, textvariable=self.max_restart_attempts, width=3
        ).grid(row=1, column=2, sticky="w", padx=(4, 14))
        ttk.Label(options, text="Vérification (s) :").grid(row=1, column=3, sticky="e")
        ttk.Spinbox(
            options, from_=1, to=300, textvariable=self.health_check_interval, width=4
        ).grid(row=1, column=4, sticky="w", padx=(4, 0))
        ttk.Button(
            options,
            text="Health check…",
            command=lambda: self._open_panel_window(
                "health", "Health check", self._build_health_panel, "620x180"
            ),
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            options,
            text="Diagnostic réseau…",
            command=lambda: self._open_panel_window(
                "network", "Diagnostic réseau", self._build_network_panel, "800x240"
            ),
        ).grid(row=2, column=1, sticky="w", padx=8, pady=(8, 0))

        security = self._collapsible_section(main, "Accès réseau", expanded=False)
        security.pack(fill="x", pady=(0, 8))
        security.columnconfigure(1, weight=1)
        security.columnconfigure(2, weight=1)
        self.allowlist_check = ttk.Checkbutton(
            security, text="Filtrer par IP/CIDR", variable=self.ip_allowlist_enabled,
            command=self._update_security_controls,
        )
        self.allowlist_check.grid(row=0, column=0, sticky="w")
        self.allowlist_entry = ttk.Entry(security, textvariable=self.allowed_ip_ranges)
        self.allowlist_entry.grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0)
        )
        self.rate_limit_check = ttk.Checkbutton(
            security, text="Limiter requêtes/minute/client", variable=self.rate_limit_enabled,
            command=self._update_security_controls,
        )
        self.rate_limit_check.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.rate_limit_spin = ttk.Spinbox(
            security, from_=1, to=10000, textvariable=self.rate_limit_requests, width=7
        )
        self.rate_limit_spin.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(5, 0))
        self.daily_upload_check = ttk.Checkbutton(
            security, text="Quota upload/jour (MiB)", variable=self.daily_upload_limit_enabled,
            command=self._update_security_controls,
        )
        self.daily_upload_check.grid(row=1, column=2, sticky="e", pady=(5, 0))
        self.daily_upload_spin = ttk.Spinbox(
            security, from_=1, to=1048576, textvariable=self.daily_upload_limit_mib, width=8
        )
        self.daily_upload_spin.grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(5, 0))
        self.https_check = ttk.Checkbutton(
            security,
            text="HTTPS automatique (Caddy)",
            variable=self.https_enabled,
            command=self._update_security_controls,
        )
        self.https_check.grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Label(security, text="Domaine public :").grid(
            row=2, column=1, sticky="e", pady=(5, 0)
        )
        self.domain_entry = ttk.Entry(security, textvariable=self.https_domain)
        self.domain_entry.grid(row=2, column=2, sticky="ew", padx=(8, 4), pady=(5, 0))
        self.dns_check_button = ttk.Button(
            security, text="Vérifier DNS", command=self._check_domain_dns, state="disabled"
        )
        self.dns_check_button.grid(row=2, column=3, sticky="ew")
        self.auth_check = ttk.Checkbutton(
            security,
            text="Authentification Basic (HTTPS/tunnel)",
            variable=self.auth_enabled,
        )
        self.auth_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.tunnel_check = ttk.Checkbutton(
            security,
            text="Tunnel Cloudflare Quick Tunnel",
            variable=self.tunnel_enabled,
            command=self._update_security_controls,
        )
        self.tunnel_check.grid(row=4, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.https_domain.trace_add("write", self._update_public_url)
        self._update_security_controls()

        actions = ttk.Frame(main, padding=(0, 4, 0, 0))
        actions.pack(fill="x", pady=(0, 7))
        ttk.Button(actions, text="Enregistrer", command=self._save_config).pack(side="left")
        ttk.Button(actions, text="Tester", command=self._test).pack(side="left", padx=7)
        self.deploy_button = ttk.Button(actions, text="DÉPLOYER", command=self._deploy)
        self.deploy_button.pack(side="right")
        self.public_access_button = ttk.Button(
            actions,
            text="COUPER L'ACCÈS PUBLIC",
            command=self._toggle_public_access,
            state="disabled",
        )
        self.public_access_button.pack(side="right", padx=7)
        self.stop_button = ttk.Button(
            actions, text="ARRÊTER", command=self._stop_deployment, state="disabled"
        )
        self.stop_button.pack(side="right", padx=7)

        status_frame = self._collapsible_section(main, "Journal", expanded=True)
        status_frame.pack(fill="both", expand=True)
        ttk.Checkbutton(
            status_frame,
            text="Afficher les logs classiques",
            variable=self.show_classic_logs,
            command=self._refresh_log_visibility
        ).pack(anchor="e", pady=(0, 6))

        log_frame = ttk.Frame(status_frame, relief="groove", padding=(8, 6))
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            height=10,
            state="disabled",
            wrap="word",
            font=("TkFixedFont", 10),
            bd=1,
            relief="sunken",
            highlightthickness=1,
        )
        # Noir = logs classiques, masqués par défaut.
        self.log.tag_configure("info", foreground="#1f2937")
        self.log.tag_configure("success", foreground="#20a040")
        self.log.tag_configure("warning", foreground="#d97706")
        self.log.tag_configure("error", foreground="#d02020")
        self.log.pack(fill="both", expand=True)

        ttk.Label(main, textvariable=self.status).pack(fill="x", pady=(5, 0))

    def _collapsible_section(self, parent, title, expanded=False):
        section = ttk.Frame(parent)
        section.pack(
            fill="both" if title == "Journal" else "x",
            expand=title == "Journal",
            pady=(0, 6),
        )
        content = ttk.Frame(section, padding=(10, 8))
        state = {"expanded": expanded}

        def toggle():
            if state["expanded"]:
                content.pack_forget()
                state["expanded"] = False
                header.configure(text=f"+  {title}")
            else:
                content.pack(fill="x", pady=(2, 0))
                state["expanded"] = True
                header.configure(text=f"-  {title}")

        header = ttk.Button(
            section,
            text=f"-  {title}" if expanded else f"+  {title}",
            command=toggle,
            style="Accent.TButton",
        )
        header.pack(fill="x")
        if expanded:
            content.pack(fill="x", pady=(2, 0))
        return content

    def _open_panel_window(self, key, title, builder, geometry):
        existing = self._panel_windows.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            return

        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(geometry)
        window.minsize(520, 160)
        self._panel_windows[key] = window
        body = ttk.Frame(window, padding=16)
        body.pack(fill="both", expand=True)
        builder(body)

    def _build_health_panel(self, parent):
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Chemin :").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.health_path).grid(
            row=0, column=1, sticky="ew", padx=(8, 16)
        )
        ttk.Label(parent, text="Code HTTP attendu :").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Spinbox(
            parent, from_=200, to=599, textvariable=self.health_expected_status, width=7
        ).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(parent, text="Timeout (s) :").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Spinbox(
            parent, from_=1, to=10, textvariable=self.health_check_timeout, width=7
        ).grid(row=2, column=1, sticky="w", padx=8)

    def _build_network_panel(self, parent):
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="IP WAN du routeur (facultatif) :").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(parent, textvariable=self.router_wan_ip).grid(
            row=0, column=1, sticky="ew", padx=(8, 10)
        )
        ttk.Button(parent, text="Analyser", command=self._run_network_diagnostics).grid(
            row=0, column=2, sticky="w"
        )
        self.network_diagnostic_output = tk.StringVar(value="")
        ttk.Label(
            parent,
            textvariable=self.network_diagnostic_output,
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))

    def _check_public_port(self):
        try:
            port = int(self.public_port.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Port invalide", "Saisissez un port compris entre 1 et 65535.")
            return
        info = check_port(port)
        if not info:
            messagebox.showinfo(
                "Port non référencé",
                f"Le port {port} n'est pas présent dans la base locale.\n\n"
                "Cela ne garantit pas qu'il soit ouvert : vérifiez aussi le pare-feu et le routeur."
            )
            return
        if info["category"] == "browser_unsafe":
            messagebox.showwarning(
                "Port déconseillé",
                f"Le port {port} est connu comme port sensible/bloqué par certains navigateurs.\n\n"
                "Choisissez plutôt 5000, 5555, 8000, 8080, 8888 ou 9000."
            )
        elif info["category"] == "router_reserved":
            messagebox.showwarning(
                "Port réseau réservé",
                f"Le port {port} ({info['name']}) est souvent réservé par des équipements réseau.\n\n"
                "Le filtrage dépend du routeur. Préférez un port Web alternatif si possible."
            )
        else:
            messagebox.showinfo("Port conseillé", f"Le port {port} est référencé comme adapté à un service Web.")

    def _update_public_url(self, *_args):
        if self.https_enabled.get() and self.https_domain.get().strip():
            self.public_url.set(f"https://{self.https_domain.get().strip()}")
            return
        try:
            port = int(self.public_port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except (ValueError, tk.TclError):
            self.public_url.set("Port public invalide")
            return

        ip = self._public_ip_value or "IP_PUBLIQUE"
        self.public_url.set(f"http://{ip}:{port}")

    def _open_public_url(self, _event=None):
        url = self.public_url.get()
        if url.startswith(("http://", "https://")) and "IP_PUBLIQUE" not in url and "..." not in url:
            webbrowser.open(url)

    def _update_security_controls(self, *_args):
        proxy_enabled = self.proxy_enabled.get()
        direct_access = self.direct_access_enabled.get()
        if direct_access and proxy_enabled:
            self.proxy_enabled.set(False)
            proxy_enabled = False
        if (not proxy_enabled or direct_access) and (self.https_enabled.get() or self.tunnel_enabled.get()):
            self.https_enabled.set(False)
            self.tunnel_enabled.set(False)
        if self.tunnel_enabled.get() and self.https_enabled.get():
            self.https_enabled.set(False)
        https_enabled = self.https_enabled.get()
        tunnel_enabled = self.tunnel_enabled.get()
        if hasattr(self, "https_check"):
            self.https_check.configure(
                state="normal" if proxy_enabled and not tunnel_enabled else "disabled"
            )
            self.tunnel_check.configure(state="normal" if proxy_enabled else "disabled")
        if hasattr(self, "domain_entry"):
            self.domain_entry.configure(state="normal" if https_enabled else "disabled")
            self.dns_check_button.configure(state="normal" if https_enabled else "disabled")
            self.auth_check.configure(
                state="normal" if https_enabled or tunnel_enabled else "disabled"
            )
            self.allowlist_check.configure(state="normal" if proxy_enabled else "disabled")
            self.allowlist_entry.configure(
                state=(
                    "normal"
                    if proxy_enabled and self.ip_allowlist_enabled.get()
                    else "disabled"
                )
            )
            self.rate_limit_check.configure(state="normal" if proxy_enabled else "disabled")
            self.rate_limit_spin.configure(
                state=(
                    "normal"
                    if proxy_enabled and self.rate_limit_enabled.get()
                    else "disabled"
                )
            )
            self.daily_upload_check.configure(state="normal" if proxy_enabled else "disabled")
            self.daily_upload_spin.configure(
                state=(
                    "normal"
                    if proxy_enabled and self.daily_upload_limit_enabled.get()
                    else "disabled"
                )
            )
        if not https_enabled and not tunnel_enabled:
            self.auth_enabled.set(False)
            self._auth_credentials = None
            try:
                if int(self.public_port.get()) == 443:
                    self.public_port.set(8000)
            except (ValueError, tk.TclError):
                self.public_port.set(8000)
        elif https_enabled:
            try:
                if int(self.public_port.get()) != 443:
                    self.public_port.set(443)
            except (ValueError, tk.TclError):
                self.public_port.set(443)
        self._update_public_url()

    def _select_proxy_access(self):
        if self.proxy_enabled.get():
            self.direct_access_enabled.set(False)
        self._update_security_controls()

    def _select_direct_access(self):
        if self.direct_access_enabled.get():
            self.proxy_enabled.set(False)
        self._update_security_controls()

    def _refresh_public_ip(self):
        try:
            from web_deploy.network.public_ip import get_public_ip
            ip = get_public_ip()
        except Exception:
            ip = None

        def apply():
            self._public_ip_value = ip
            self.public_ip.set(f"IP publique : {ip}" if ip else "IP publique : indisponible")
            self._update_public_url()

        self.root.after(0, apply)
        self.root.after(300000, self._refresh_public_ip)

    def _check_domain_dns(self):
        domain = self.https_domain.get().strip()
        try:
            result = resolve_domain(domain, self._public_ip_value)
        except ValueError as exc:
            messagebox.showwarning("Vérification DNS", str(exc))
            return

        addresses = ", ".join(result.addresses)
        if self._public_ip_value is None:
            messagebox.showinfo(
                "Vérification DNS",
                f"{result.domain} résout vers {addresses}. IP publique non détectée : comparaison impossible.",
            )
        elif result.matches:
            messagebox.showinfo(
                "Vérification DNS",
                f"{result.domain} pointe vers l'IP publique détectée ({addresses}).",
            )
        else:
            messagebox.showwarning(
                "Vérification DNS",
                f"{result.domain} résout vers {addresses}, au lieu de {result.expected_ip}.",
            )

    def _run_network_diagnostics(self):
        proxy_listening = None
        if self.deployer and self.deployer.proxy:
            proxy_port = 443 if self.https_enabled.get() else int(self.public_port.get())
            proxy_listening, _error = check_tcp_listener("127.0.0.1", proxy_port)

        findings = diagnose_network(
            local_ip=self._get_local_ip(),
            public_ip=self._public_ip_value,
            router_wan_ip=self.router_wan_ip.get().strip() or None,
            proxy_listening=proxy_listening,
        )
        self.network_diagnostic_output.set(
            "\n".join(
                f"{finding.title} — {finding.detail} Prochaine étape : {finding.next_step}"
                for finding in findings
            )
        )

    def _refresh_dashboard(self):
        if self.deployer is None:
            server_status = "arrêté"
            proxy_status = "coupé" if self.proxy_enabled.get() else "désactivé"
            https_status = "activé" if self.https_enabled.get() else "non"
            tunnel_status = "activé" if self.tunnel_enabled.get() else "non"
            last_health = "non vérifié"
        else:
            snapshot = self.deployer.status_snapshot()
            server_status = snapshot["server"]
            proxy_status = snapshot["proxy"]
            https_status = "actif" if snapshot["https"] else "non"
            tunnel_status = "actif" if snapshot.get("tunnel") else "non"
            last_health = snapshot["last_health_result"]
            if snapshot["last_health_check"]:
                last_health = f"{snapshot['last_health_check']} · {last_health}"
            if snapshot.get("public_url"):
                self.public_url.set(snapshot["public_url"])
            else:
                self._update_public_url()

        self.dashboard_state.set(
            f"Serveur : {server_status} | Proxy Caddy : {proxy_status} | "
            f"HTTPS : {https_status} | Tunnel : {tunnel_status} | Santé : {last_health}"
        )
        if self.root.winfo_exists():
            self.root.after(1000, self._refresh_dashboard)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Choisir le fichier Python du serveur",
            filetypes=[("Python", "*.py"), ("Tous les fichiers", "*.*")]
        )
        if path:
            self.server_file.set(os.path.relpath(path, os.getcwd()))

    def _detect_server(self):
        result = detect_server(os.getcwd(), self.server_file.get().strip() or None)
        if result.framework == "unknown":
            messagebox.showinfo(
                "Détection serveur",
                "Aucun framework ou point d'entrée courant n'a été reconnu. "
                "La sélection manuelle reste disponible.",
            )
            return

        if result.server_file:
            self.server_file.set(result.server_file)
        if result.application:
            self.module_name.set(result.application)
        self.server_module.set(result.server_module or "")
        self.server_args.set(shlex.join(result.server_args))
        if result.port:
            self.port.set(result.port)

        messagebox.showinfo(
            "Détection serveur",
            f"Framework : {result.framework}\n"
            f"Fichier : {result.server_file or 'à choisir'}\n"
            f"Port proposé : {result.port or 'à choisir'}\n"
            f"Confiance : {result.confidence}\n"
            f"Commande suggérée : {result.command_hint}\n\n"
            "Vérifie et corrige les champs avant le déploiement.",
        )

    def _config_dict(self):
        return {
            "server_file": self.server_file.get().strip(),
            "module_name": self.module_name.get().strip(),
            "server_module": self.server_module.get().strip() or None,
            "server_args": shlex.split(self.server_args.get()),
            "host": self.host.get().strip(),
            "port": int(str(self.port.get()).strip()),
            "public_port": int(str(self.public_port.get()).strip()),
            "proxy_enabled": bool(self.proxy_enabled.get()),
            "direct_access_enabled": bool(self.direct_access_enabled.get()),
            "auto_start": bool(self.auto_start.get()),
            "auto_restart": bool(self.auto_restart.get()),
            "max_restart_attempts": int(self.max_restart_attempts.get()),
            "health_check_interval": int(self.health_check_interval.get()),
            "health_check_timeout": int(self.health_check_timeout.get()),
            "health_path": self.health_path.get().strip() or "/",
            "health_expected_status": int(self.health_expected_status.get()),
            "allowed_ip_ranges": [
                value.strip()
                for value in self.allowed_ip_ranges.get().split(",")
                if value.strip()
            ],
            "ip_allowlist_enabled": bool(self.ip_allowlist_enabled.get()),
            "rate_limit_enabled": bool(self.rate_limit_enabled.get()),
            "rate_limit_requests": int(self.rate_limit_requests.get()),
            "rate_limit_window_seconds": 60,
            "daily_upload_limit_enabled": bool(self.daily_upload_limit_enabled.get()),
            "daily_upload_limit_mib": int(self.daily_upload_limit_mib.get()),
            "https_enabled": bool(self.https_enabled.get()),
            "https_domain": self.https_domain.get().strip(),
            "tunnel_enabled": bool(self.tunnel_enabled.get()),
            "router_wan_ip": self.router_wan_ip.get().strip(),
            "auth_enabled": bool(self.auth_enabled.get()),
            "use_venv": bool(self.use_venv.get()),
            "venv_name": ".venv",
            "project_root": os.getcwd()
        }

    def _save_config(self):
        try:
            cfg = self._config_dict()
            if not cfg["server_file"]:
                raise ValueError("Sélectionne d'abord le fichier Python du serveur.")
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
            self._log(f"[OK] Configuration enregistrée dans {CONFIG_FILE}")
            self.status.set("Configuration enregistrée.")
        except Exception as exc:
            messagebox.showerror("Configuration", str(exc))

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            self.server_file.set(cfg.get("server_file", ""))
            self.module_name.set(cfg.get("module_name", "app"))
            self.server_module.set(cfg.get("server_module", "") or "")
            server_args = cfg.get("server_args", [])
            self.server_args.set(shlex.join(server_args) if isinstance(server_args, list) else str(server_args))
            self.host.set(cfg.get("host", "127.0.0.1"))
            self.port.set(cfg.get("port", 5555))
            self.public_port.set(cfg.get("public_port", 8000))
            self.proxy_enabled.set(cfg.get("proxy_enabled", True))
            self.direct_access_enabled.set(cfg.get("direct_access_enabled", False))
            self.auto_start.set(cfg.get("auto_start", True))
            self.auto_restart.set(cfg.get("auto_restart", False))
            self.max_restart_attempts.set(cfg.get("max_restart_attempts", 3))
            self.health_check_interval.set(cfg.get("health_check_interval", 10))
            self.health_check_timeout.set(cfg.get("health_check_timeout", 3))
            self.health_path.set(cfg.get("health_path", "/"))
            self.health_expected_status.set(cfg.get("health_expected_status", 200))
            allowed_ip_ranges = cfg.get("allowed_ip_ranges", [])
            if isinstance(allowed_ip_ranges, str):
                allowed_ip_ranges = allowed_ip_ranges.split(",")
            self.allowed_ip_ranges.set(", ".join(allowed_ip_ranges))
            self.ip_allowlist_enabled.set(
                cfg.get("ip_allowlist_enabled", bool(allowed_ip_ranges))
            )
            self.rate_limit_enabled.set(cfg.get("rate_limit_enabled", True))
            self.rate_limit_requests.set(cfg.get("rate_limit_requests", 120))
            self.daily_upload_limit_enabled.set(cfg.get("daily_upload_limit_enabled", False))
            self.daily_upload_limit_mib.set(cfg.get("daily_upload_limit_mib", 1024))
            self.https_enabled.set(cfg.get("https_enabled", False))
            self.https_domain.set(cfg.get("https_domain", ""))
            self.tunnel_enabled.set(cfg.get("tunnel_enabled", False))
            self.router_wan_ip.set(cfg.get("router_wan_ip", ""))
            self.auth_enabled.set(cfg.get("auth_enabled", False))
            self.use_venv.set(cfg.get("use_venv", True))
            self._update_security_controls()
            self._update_public_url()
            self._log(f"[OK] Configuration chargée depuis {CONFIG_FILE}")
        except Exception as exc:
            self._log(f"[ERREUR] Impossible de charger la configuration : {exc}")

    def _make_deployer(self):
        config = self._config_dict()
        if self.auth_enabled.get() and self._auth_credentials:
            config["auth_credentials"] = self._auth_credentials
        return Deployer(config, self._log)

    def _test(self):
        try:
            deployer = self._make_deployer()
            result = deployer.validate()
            self._log("[OK] " + result)
            self.status.set("Test terminé.")
        except Exception as exc:
            self._log("[ERREUR] " + str(exc))
            messagebox.showerror("Test", str(exc))

    def _deploy(self):
        if self._deployment_in_progress or self._services_active:
            return
        if self.direct_access_enabled.get():
            warning = (
                "L'application écoutera directement sur toutes les interfaces, sans Caddy, "
                "sans HTTPS et sans filtrage réseau du kit. Toute personne pouvant joindre "
                "le port pourra y accéder. Configure une redirection WAN vers le port serveur "
                "et continue uniquement si tu acceptes ces risques. Continuer ?"
            )
            if not messagebox.askyesno("Confirmer l'accès direct", warning):
                return
        elif self.proxy_enabled.get():
            if self.tunnel_enabled.get():
                warning = (
                    "Cloudflare Quick Tunnel va créer une URL HTTPS temporaire. "
                    "Le trafic public transitera par Cloudflare ; l'URL est éphémère, "
                    "sans SLA et destinée au développement/test. Continuer ?"
                )
            elif self.https_enabled.get():
                warning = (
                    "Le domaine doit pointer vers cette machine et les ports TCP 80/443 "
                    "doivent être accessibles depuis Internet. Caddy obtiendra le certificat. "
                    + (
                        " Les visiteurs devront aussi s'authentifier. Continuer ?"
                        if self.auth_enabled.get()
                        else " L'authentification n'est pas activée ; toute personne pourra accéder à l'application. Continuer ?"
                    )
                )
            else:
                warning = (
                    "Cette application sera accessible depuis Internet en HTTP non chiffré. "
                    "HTTPS et l'authentification ne seront pas actifs. N'expose pas de données sensibles. "
                    "Continuer ?"
                )
            if not messagebox.askyesno("Confirmer l'exposition publique", warning):
                return
        if self.auth_enabled.get():
            if not self.https_enabled.get():
                messagebox.showerror("Authentification", "Active HTTPS avant l'authentification Basic.")
                return
            username = simpledialog.askstring(
                "Authentification Basic", "Identifiant :", parent=self.root
            )
            if username is None:
                return
            password = simpledialog.askstring(
                "Authentification Basic", "Mot de passe :", show="*", parent=self.root
            )
            if password is None or not username or not password:
                return
            self._auth_credentials = {"username": username, "password": password}
        self._save_config()
        try:
            self.deployer = self._make_deployer()
            self._deployment_in_progress = True
            self.deploy_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.status.set("Déploiement en cours...")
            threading.Thread(target=self._deploy_worker, daemon=True).start()
        except Exception as exc:
            self._deployment_in_progress = False
            self.deploy_button.configure(state="normal")
            messagebox.showerror("Déploiement", str(exc))

    def _deploy_worker(self):
        succeeded = False
        cleanup_succeeded = True
        try:
            self.deployer.deploy()
            succeeded = True
        except Exception as exc:
            self._log("[ERREUR] " + str(exc))
            cleanup_succeeded = self.deployer.stop()

        self._deployment_in_progress = False
        self._services_active = succeeded or not cleanup_succeeded
        if not succeeded and cleanup_succeeded:
            self._auth_credentials = None
        if self._closing:
            if succeeded:
                cleanup_succeeded = self.deployer.stop()
            if cleanup_succeeded:
                self._services_active = False
                self.root.after(0, self.root.destroy)
            else:
                self.root.after(0, self._confirm_force_stop)
        else:
            status = "Déploiement terminé." if succeeded else "Échec du déploiement."
            self.root.after(0, lambda: self.status.set(status))
            self.root.after(0, self._update_deployment_buttons)

    def _update_deployment_buttons(self):
        self.deploy_button.configure(
            state="disabled" if self._services_active or self._deployment_in_progress else "normal"
        )
        self.stop_button.configure(state="normal" if self._services_active else "disabled")
        public_active = bool(self.deployer and self.deployer.proxy is not None)
        direct_active = bool(
            self.deployer
            and self.deployer.config.get("direct_access_enabled", False)
            and self._services_active
        )
        self.public_access_button.configure(
            text=(
                "ACCÈS DIRECT ACTIF"
                if direct_active
                else "COUPER L'ACCÈS PUBLIC"
                if public_active
                else "ACTIVER LE PROXY PUBLIC"
                if not self.proxy_enabled.get()
                else "RÉTABLIR L'ACCÈS PUBLIC"
            ),
            state=(
                "normal"
                if self._services_active
                and not self._public_access_operation
                and not direct_active
                else "disabled"
            ),
        )

    def _toggle_public_access(self):
        if not self._services_active or self._public_access_operation:
            return
        if self.deployer and self.deployer.config.get("direct_access_enabled", False):
            return
        if (
            self.deployer
            and self.deployer.proxy is None
            and not self.deployer.config.get("proxy_enabled", True)
        ):
            warning = (
                "Caddy va ouvrir le proxy public sur le port configuré. "
                "En HTTP, le trafic ne sera pas chiffré. Toute personne pouvant joindre "
                "ce port pourra accéder à l'application. Continuer ?"
            )
            if not messagebox.askyesno("Confirmer l'exposition publique", warning):
                return
        if self.tunnel_enabled.get() and self.deployer and self.deployer.proxy is None:
            if not messagebox.askyesno(
                "Activer le tunnel public",
                "Le trafic transitera par Cloudflare et une nouvelle URL temporaire sera créée. Continuer ?",
            ):
                return
        self._public_access_operation = True
        self.public_access_button.configure(state="disabled")
        threading.Thread(target=self._toggle_public_access_worker, daemon=True).start()

    def _toggle_public_access_worker(self):
        error_message = None
        try:
            if self.deployer.proxy is None:
                enabling_proxy = not self.deployer.config.get("proxy_enabled", True)
                if enabling_proxy:
                    self.deployer.config["proxy_enabled"] = True
                try:
                    if enabling_proxy:
                        self.deployer.validate()
                    self.deployer.start_public_access()
                except Exception:
                    if enabling_proxy:
                        self.deployer.config["proxy_enabled"] = False
                    raise
                if enabling_proxy:
                    self.root.after(0, self._sync_proxy_enabled)
                status = "Accès public rétabli."
            else:
                if not self.deployer.stop_public_access():
                    raise RuntimeError("L'accès public n'a pas pu être coupé proprement.")
                status = "Accès public coupé ; le serveur local reste actif."
        except Exception as exc:
            error_message = str(exc)
            self._log(f"[ERREUR] {error_message}")
            status = "Échec de la modification de l'accès public."

        self._public_access_operation = False
        if self._closing:
            if self.deployer.stop():
                self._services_active = False
                self.root.after(0, self.root.destroy)
            else:
                self.root.after(0, self._confirm_force_stop)
            return
        self.root.after(0, lambda: self.status.set(status))
        self.root.after(0, self._update_deployment_buttons)
        if error_message:
            self.root.after(
                0,
                lambda message=error_message: messagebox.showerror(
                    "Accès public", message, parent=self.root
                ),
            )

    def _sync_proxy_enabled(self):
        self.proxy_enabled.set(True)
        self._update_security_controls()

    def _stop_deployment(self):
        if not self._services_active or self._deployment_in_progress:
            return
        self.stop_button.configure(state="disabled")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self, force=False):
        stopped = self.deployer.stop(force=force)
        self._services_active = not stopped
        if stopped:
            self._auth_credentials = None
        if not stopped and not force:
            self.root.after(0, self._confirm_force_stop)
            return
        if not stopped:
            if self._closing:
                self._closing = False
            self.root.after(0, lambda: self.status.set("Arrêt incomplet ; vérifie les logs."))
            self.root.after(0, self._update_deployment_buttons)
            return
        if self._closing and stopped:
            self.root.after(0, self.root.destroy)
            return
        self.root.after(0, lambda: self.status.set("Services arrêtés."))
        self.root.after(0, self._update_deployment_buttons)

    def _confirm_force_stop(self):
        confirmed = messagebox.askyesno(
            "Confirmer l'arrêt forcé",
            "L'arrêt normal n'a pas abouti. Forcer l'arrêt du processus serveur "
            "démarré par Web Deployer ?",
        )
        if confirmed:
            threading.Thread(
                target=self._stop_worker,
                kwargs={"force": True},
                daemon=True,
            ).start()
            return
        if self._closing:
            self._closing = False
        self.status.set("Arrêt non confirmé ; le serveur peut toujours fonctionner.")
        self._update_deployment_buttons()

    def _on_close(self):
        if self._deployment_in_progress:
            self._closing = True
            self.status.set("Fermeture après la fin du déploiement...")
            return
        if self._public_access_operation:
            self._closing = True
            self.status.set("Fermeture après la mise à jour de l'accès public...")
            return
        if self._services_active:
            self._closing = True
            self.stop_button.configure(state="disabled")
            threading.Thread(target=self._stop_worker, daemon=True).start()
            return
        self.root.destroy()

    def _refresh_log_visibility(self):
        """Recharge l'affichage du journal selon le filtre demandé.

        Les lignes sont conservées dans une mémoire interne afin de pouvoir
        afficher/masquer les logs classiques sans perdre les messages utiles.
        """
        if not hasattr(self, "_log_history"):
            return

        def write():
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            for text, tag in self._log_history:
                if tag == "info" and not self.show_classic_logs.get():
                    continue
                self.log.insert("end", text + "\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")

        self.root.after(0, write)

    def _log(self, message):
        text = str(message)
        upper = text.upper()
        if "[ERREUR]" in upper:
            tag = "error"
        elif "[ATTENTION]" in upper or "[WARN]" in upper or "[SOLUTION]" in upper:
            tag = "warning"
        elif "[OK]" in upper or "[SUCCÈS]" in upper:
            tag = "success"
        else:
            tag = "info"

        level = {
            "error": "error",
            "warning": "warning",
            "success": "info",
            "info": "info",
        }[tag]
        getattr(self.file_logger, level)(text)

        if not hasattr(self, "_log_history"):
            self._log_history = []
        self._log_history.append((text, tag))
        # Évite une croissance infinie du journal en mémoire.
        if len(self._log_history) > 1000:
            del self._log_history[:-1000]

        def write():
            if tag == "info" and not self.show_classic_logs.get():
                return
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, write)

    def run(self):
        self.root.mainloop()
