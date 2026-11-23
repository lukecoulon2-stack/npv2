import os
import subprocess
import sys
import venv
from pathlib import Path


class DependencyManager:
    """Crée et prépare un environnement virtuel pour le projet."""

    def __init__(self, project_root, log=print, venv_name=".venv"):
        self.project_root = Path(project_root).resolve()
        self.log = log
        self.venv_dir = self.project_root / venv_name

    @property
    def python(self):
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    def _run(self, args, description, summary=None):
        self.log(f"[INFO] {description}...")
        result = subprocess.run(
            [str(arg) for arg in args],
            cwd=str(self.project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or "").strip().splitlines()
            detail = details[-1] if details else "aucun détail"
            raise RuntimeError(f"{description} a échoué (code {result.returncode}) : {detail}")
        if summary:
            self.log(f"[OK] {summary}")

    @staticmethod
    def _count_requirements(path):
        count = 0
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                count += 1
        return count

    def prepare(self):
        if not self.venv_dir.exists():
            self.log(f"[INFO] Création du venv : {self.venv_dir}")
            builder = venv.EnvBuilder(with_pip=True, clear=False, upgrade=False)
            builder.create(str(self.venv_dir))
            self.log("[OK] Environnement virtuel créé.")
        else:
            self.log(f"[INFO] Environnement virtuel existant : {self.venv_dir}")

        if not self.python.exists():
            raise RuntimeError(f"Python du venv introuvable : {self.python}")

        self._run(
            [self.python, "-m", "pip", "install", "--upgrade", "pip"],
            "Mise à jour de pip",
            "pip prêt",
        )

        requirements = self.project_root / "requirements.txt"
        pyproject = self.project_root / "pyproject.toml"
        setup_py = self.project_root / "setup.py"

        if requirements.is_file():
            total = self._count_requirements(requirements)
            self._run(
                [self.python, "-m", "pip", "install", "-r", requirements],
                "Installation des dépendances",
                f"Dépendances installées : {total}/{total}" if total else "Aucune dépendance déclarée",
            )
        elif pyproject.is_file() or setup_py.is_file():
            self._run(
                [self.python, "-m", "pip", "install", "."],
                "Installation du projet et de ses dépendances",
                "Dépendances du projet installées",
            )
        else:
            self.log("[WARN] Aucune liste de dépendances trouvée ; venv prêt.")

        self.log(f"[OK] Environnement prêt : {self.venv_dir}")
        return str(self.python)
