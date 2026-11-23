#!/usr/bin/env python3
"""Point d'entrée du kit Web Deployer."""
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from web_deploy.ui.config_ui import ConfigUI


def choose_version():
    root = tk.Tk()
    root.title("Web Deploy Kit")
    root.geometry("420x190")
    root.resizable(False, False)

    ttk.Label(root, text="Choisir une version", font=("TkDefaultFont", 15, "bold")).pack(
        pady=(24, 8)
    )
    ttk.Label(root, text="Sélectionnez le niveau de configuration souhaité.").pack(
        pady=(0, 18)
    )

    actions = ttk.Frame(root)
    actions.pack()

    def launch_simple():
        script = Path(__file__).parent / "web_deploy" / "simple_version" / "deploy.py"
        subprocess.Popen([sys.executable, str(script)], cwd=os.getcwd())
        root.destroy()

    def launch_advanced():
        root.destroy()
        ConfigUI().run()

    ttk.Button(actions, text="Version simple", command=launch_simple).pack(
        side="left", padx=8
    )
    ttk.Button(actions, text="Version avancée", command=launch_advanced).pack(
        side="left", padx=8
    )
    root.mainloop()


if __name__ == "__main__":
    choose_version()
