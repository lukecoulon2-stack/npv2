import json
import os
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from web_deploy.core.deployer import Deployer
from web_deploy.core.port_database import check_port, initialize_database

CONFIG_FILE = "web_deploy_config.json"


class ConfigUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Web Deployer")
        self.root.geometry("760x680")
        self.root.minsize(740, 640)

        self.server_file = tk.StringVar()
        self.module_name = tk.StringVar(value="app")
        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.IntVar(value=5555)
        self.public_port = tk.IntVar(value=8000)
        self.auto_start = tk.BooleanVar(value=True)
        self.proxy_enabled = tk.BooleanVar(value=True)
        self.use_venv = tk.BooleanVar(value=True)
        self.show_classic_logs = tk.BooleanVar(value=False)

        self.status = tk.StringVar(value="Prêt.")
        self.public_ip = tk.StringVar(value="IP publique : détection...")
        self.public_url = tk.StringVar(value="http://...:8080")
        self.deployer = None
        self._public_ip_value = None
        initialize_database()
        self._show_tutorial()

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

    def _build(self):
        main = ttk.Frame(self.root, padding=(14, 12))
        main.pack(fill="both", expand=True)

        # En-tête compact : le lien public reste toujours visible.
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="WEB DEPLOYER", font=("TkDefaultFont", 17, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.public_ip).pack(side="right", padx=(10, 0))

        public_box = ttk.Frame(main, relief="groove", padding=(10, 7))
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

        form = ttk.LabelFrame(main, text="Application", padding=(10, 7))
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Fichier du serveur :").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.server_file).grid(row=0, column=1, sticky="ew", padx=7)
        ttk.Button(form, text="Parcourir…", command=self._browse).grid(row=0, column=2, padx=(2, 0))

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

        options = ttk.LabelFrame(main, text="Options", padding=(10, 6))
        options.pack(fill="x", pady=8)
        ttk.Checkbutton(options, text="Proxy public", variable=self.proxy_enabled).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(options, text="Venv + dépendances", variable=self.use_venv).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(options, text="Démarrage automatique", variable=self.auto_start).pack(side="left")

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(0, 7))
        ttk.Button(actions, text="Enregistrer", command=self._save_config).pack(side="left")
        ttk.Button(actions, text="Tester", command=self._test).pack(side="left", padx=7)
        ttk.Button(actions, text="DÉPLOYER", command=self._deploy).pack(side="right")

        status_header = ttk.Frame(main)
        status_header.pack(fill="x")
        ttk.Label(status_header, text="Journal").pack(side="left")
        ttk.Checkbutton(
            status_header,
            text="Afficher les logs classiques",
            variable=self.show_classic_logs,
            command=self._refresh_log_visibility
        ).pack(side="right")

        status_frame = ttk.Frame(main, relief="groove", padding=(7, 5))
        status_frame.pack(fill="both", expand=True)
        self.log = tk.Text(status_frame, height=7, state="disabled", wrap="word")
        # Noir = logs classiques, masqués par défaut.
        self.log.tag_configure("info", foreground="#000000")
        self.log.tag_configure("success", foreground="#20a040")
        self.log.tag_configure("warning", foreground="#d97706")
        self.log.tag_configure("error", foreground="#d02020")
        self.log.pack(fill="both", expand=True)

        ttk.Label(main, textvariable=self.status).pack(fill="x", pady=(5, 0))

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
        if url.startswith("http://") and "IP_PUBLIQUE" not in url and "..." not in url:
            webbrowser.open(url)

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

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Choisir le fichier Python du serveur",
            filetypes=[("Python", "*.py"), ("Tous les fichiers", "*.*")]
        )
        if path:
            self.server_file.set(os.path.relpath(path, os.getcwd()))

    def _config_dict(self):
        return {
            "server_file": self.server_file.get().strip(),
            "module_name": self.module_name.get().strip(),
            "host": self.host.get().strip(),
            "port": int(str(self.port.get()).strip()),
            "public_port": int(str(self.public_port.get()).strip()),
            "proxy_enabled": bool(self.proxy_enabled.get()),
            "auto_start": bool(self.auto_start.get()),
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
            self.host.set(cfg.get("host", "127.0.0.1"))
            self.port.set(cfg.get("port", 5555))
            self.public_port.set(cfg.get("public_port", 8000))
            self.proxy_enabled.set(cfg.get("proxy_enabled", True))
            self.auto_start.set(cfg.get("auto_start", True))
            self.use_venv.set(cfg.get("use_venv", True))
            self._update_public_url()
            self._log(f"[OK] Configuration chargée depuis {CONFIG_FILE}")
        except Exception as exc:
            self._log(f"[ERREUR] Impossible de charger la configuration : {exc}")

    def _make_deployer(self):
        return Deployer(self._config_dict(), self._log)

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
        self._save_config()
        try:
            self.deployer = self._make_deployer()
            self.status.set("Déploiement en cours...")
            threading.Thread(target=self._deploy_worker, daemon=True).start()
        except Exception as exc:
            messagebox.showerror("Déploiement", str(exc))

    def _deploy_worker(self):
        try:
            self.deployer.deploy()
            self.status.set("Déploiement terminé.")
        except Exception as exc:
            self._log("[ERREUR] " + str(exc))
            self.status.set("Échec du déploiement.")

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
