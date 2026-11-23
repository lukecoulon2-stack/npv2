"""Stage a source-only release and install it before the next server launch."""
import ast
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory


REPOSITORY = "https://github.com/lukecoulon2-stack/npv2.git"
WORK_DIRECTORY = ".naoning-update"
REQUIRED = {
    Path("start.py"), Path("requirements.txt"), Path("planning/web.py"),
    Path("planning/templates/index.html"), Path("planning/static/app.js"),
}
SOURCE_TYPES = {
    "static": {".css", ".js", ".png", ".webp", ".ico", ".svg", ".woff2", ".webmanifest"},
    "templates": {".html"},
}


def source_paths(directory):
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        parts = relative.parts
        allowed = relative in REQUIRED or relative == Path("README.md") or (
            parts[0] == "planning" and (
                len(parts) == 2 and path.suffix == ".py"
                or len(parts) >= 3 and path.suffix in SOURCE_TYPES.get(parts[1], set())
            )
        )
        if allowed and path.is_file():
            if any((directory / Path(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)):
                raise ValueError(f"Lien symbolique dans les sources GitHub ({relative}).")
            yield relative


def validate_sources(directory):
    paths = list(source_paths(directory))
    if not REQUIRED.issubset(paths):
        raise ValueError("GitHub ne contient pas encore les sources complètes de Planneli.")
    try:
        for relative in paths:
            if relative.suffix == ".py":
                ast.parse((directory / relative).read_bytes(), filename=str(relative))
    except SyntaxError as error:
        raise ValueError(f"Source Python invalide dans GitHub ({error.filename}).") from error
    return paths


def pending_revision(project):
    marker = project / WORK_DIRECTORY / "pending" / "revision"
    return marker.read_text(encoding="ascii").strip() if marker.is_file() else None


def fetch_release(project):
    directory = project / WORK_DIRECTORY
    directory.mkdir(mode=0o700, exist_ok=True)
    if pending_revision(project):
        raise ValueError("Une mise à jour est déjà prête. Redémarrez Planneli pour l’appliquer.")
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=directory, env=environment, check=True,
            capture_output=True, text=True, timeout=50,
        ).stdout.strip()

    with TemporaryDirectory(prefix="fetch-", dir=directory) as temporary:
        checkout = Path(temporary) / "checkout"
        release = Path(temporary) / "release"
        try:
            git("clone", "--quiet", "--depth", "1", "--no-tags", "--", REPOSITORY, str(checkout))
            paths = validate_sources(checkout)
            revision = git("-C", str(checkout), "rev-parse", "HEAD")
        except FileNotFoundError as error:
            raise ValueError("Git doit être installé sur le serveur.") from error
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError("Impossible de récupérer le dépôt GitHub. Vérifiez son accès et sa branche principale.") from error

        if (directory / "installed").is_file() and (directory / "installed").read_text().strip() == revision:
            return None
        for relative in paths:
            target = release / "sources" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkout / relative, target)
        (release / "revision").write_text(revision, encoding="ascii")
        release.rename(directory / "pending")
        return revision


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        path = Path(temporary.name)
    try:
        shutil.copy2(source, path)
        os.replace(path, target)
    finally:
        path.unlink(missing_ok=True)


def apply_pending(project):
    revision = pending_revision(project)
    if not revision:
        return None
    workspace = project / WORK_DIRECTORY
    pending = workspace / "pending"
    sources = pending / "sources"
    paths = validate_sources(sources)
    originals = pending / "originals"
    for relative in paths:
        target = project / relative
        if any((project / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            raise ValueError(f"Lien symbolique dans les sources locales ({relative}).")
        if target.exists() and not target.is_file():
            raise ValueError(f"Impossible de remplacer le chemin {relative}.")
    if not (pending / "prepared").exists():
        for relative in paths:
            target = project / relative
            if target.is_file():
                atomic_copy(target, originals / relative)
        (pending / "prepared").touch()
    try:
        # The bootstrap is installed last so an interrupted update can resume on startup.
        for relative in sorted(paths, key=lambda item: item == Path("start.py")):
            target = project / relative
            atomic_copy(sources / relative, target)
            if target.suffix == ".py":
                Path(importlib.util.cache_from_source(str(target))).unlink(missing_ok=True)
        atomic_copy(pending / "revision", workspace / "installed")
    except OSError:
        for relative in paths:
            original = originals / relative
            if original.is_file():
                atomic_copy(original, project / relative)
            else:
                (project / relative).unlink(missing_ok=True)
        raise
    with TemporaryDirectory(prefix="applied-", dir=workspace) as temporary:
        pending.rename(Path(temporary) / "release")
    return revision
