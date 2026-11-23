import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None


@dataclass(frozen=True)
class ServerDetection:
    framework: str
    server_file: str | None
    port: int | None
    application: str | None
    server_module: str | None
    server_args: tuple[str, ...]
    command_hint: str
    confidence: str


_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"}
_DEFAULT_PORTS = {"flask": 5000, "fastapi": 8000, "django": 8000}


def _dependency_names(project_root):
    names = set()
    requirements = project_root / "requirements.txt"
    if requirements.is_file():
        for line in requirements.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split(";", 1)[0].strip()
            match = re.match(r"([A-Za-z0-9_.-]+)", line)
            if match:
                names.add(match.group(1).lower().replace("_", "-"))

    pyproject = project_root / "pyproject.toml"
    if tomllib and pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        project_deps = data.get("project", {}).get("dependencies", [])
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for dependency in project_deps:
            match = re.match(r"([A-Za-z0-9_.-]+)", dependency)
            if match:
                names.add(match.group(1).lower().replace("_", "-"))
        names.update(str(name).lower().replace("_", "-") for name in poetry_deps)
    return names


def _python_files(project_root, selected_file=None):
    files = []
    if selected_file:
        selected = Path(selected_file)
        if not selected.is_absolute():
            selected = project_root / selected
        if selected.is_file() and selected.suffix == ".py":
            files.append(selected.resolve())

    for current, dirs, filenames in os.walk(project_root):
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not name.startswith(".")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(current) / filename
            if path in files:
                continue
            try:
                if path.stat().st_size <= 1024 * 1024:
                    files.append(path)
            except OSError:
                continue
            if len(files) >= 500:
                return files
    return files


def _analyze(path):
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return {"frameworks": set(), "port": None, "application": None, "run_call": False}

    frameworks = set()
    application = None
    port = None
    run_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            frameworks.update(alias.name.split(".", 1)[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            frameworks.add(node.module.split(".", 1)[0].lower())
        elif isinstance(node, ast.Assign):
            value = node.value
            if isinstance(value, ast.Call):
                called = value.func.id if isinstance(value.func, ast.Name) else ""
                if called in ("Flask", "FastAPI"):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            application = target.id
                            frameworks.add(called.lower())
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute) and function.attr == "run":
                run_call = True
            for keyword in node.keywords:
                if keyword.arg == "port" and isinstance(keyword.value, ast.Constant):
                    value = keyword.value.value
                    if isinstance(value, int) and 1 <= value <= 65535:
                        port = value
    return {"frameworks": frameworks, "port": port, "application": application, "run_call": run_call}


def detect_server(project_root, selected_file=None):
    root = Path(project_root).resolve()
    files = _python_files(root, selected_file)
    analyses = [(path, _analyze(path)) for path in files]
    dependencies = _dependency_names(root)
    imports = set().union(*(analysis["frameworks"] for _path, analysis in analyses)) if analyses else set()

    manage_py = root / "manage.py"
    if manage_py.is_file() and ("django" in dependencies or "django" in imports):
        framework = "django"
    elif "fastapi" in dependencies or "fastapi" in imports:
        framework = "fastapi"
    elif "flask" in dependencies or "flask" in imports:
        framework = "flask"
    else:
        framework = "unknown"

    selected_path = None
    if selected_file:
        candidate = Path(selected_file)
        selected_path = candidate if candidate.is_absolute() else root / candidate
        selected_path = selected_path.resolve()

    if framework == "django" and manage_py.is_file():
        entrypoint = manage_py
    elif selected_path in [path for path, _analysis in analyses]:
        entrypoint = selected_path
    else:
        preferred = {
            "flask": ("app.py", "application.py", "server.py", "main.py"),
            "fastapi": ("main.py", "app.py", "server.py"),
            "django": ("manage.py",),
            "unknown": (),
        }[framework]
        ranked = sorted(
            analyses,
            key=lambda item: (
                Path(item[0]).name not in preferred,
                not item[1]["run_call"],
                len(item[0].relative_to(root).parts),
                str(item[0]),
            ),
        )
        entrypoint = ranked[0][0] if ranked and (preferred or ranked[0][1]["run_call"]) else None

    selected_analysis = next(
        (analysis for path, analysis in analyses if path == entrypoint),
        {"port": None, "application": None, "run_call": False},
    )
    port = selected_analysis["port"] or _DEFAULT_PORTS.get(framework)
    application = selected_analysis["application"] or "app"
    server_module = None
    server_args = ()

    if framework == "django" and entrypoint:
        server_args = ("runserver", "{host}:{port}")
        command_hint = "python manage.py runserver {host}:{port}"
    elif framework == "fastapi" and entrypoint:
        if selected_analysis["run_call"]:
            command_hint = f"python {entrypoint.relative_to(root)}"
        else:
            server_module = "uvicorn"
            module_name = ".".join(entrypoint.relative_to(root).with_suffix("").parts)
            server_args = (f"{module_name}:{application}", "--host", "{host}", "--port", "{port}")
            command_hint = f"python -m uvicorn {module_name}:{application} --host {{host}} --port {{port}}"
    elif framework == "flask" and entrypoint:
        if selected_analysis["run_call"]:
            command_hint = f"python {entrypoint.relative_to(root)}"
        else:
            server_module = "flask"
            module_name = ".".join(entrypoint.relative_to(root).with_suffix("").parts)
            server_args = ("--app", f"{module_name}:{application}", "run", "--host", "{host}", "--port", "{port}")
            command_hint = f"python -m flask --app {module_name}:{application} run --host {{host}} --port {{port}}"
    else:
        command_hint = "Aucun point d'entrée de framework reconnu ; sélection manuelle requise."

    if entrypoint and framework != "unknown":
        confidence = "élevée" if selected_analysis["application"] or framework == "django" else "moyenne"
        server_file = str(entrypoint.relative_to(root))
    else:
        confidence = "faible"
        server_file = None

    return ServerDetection(
        framework=framework,
        server_file=server_file,
        port=port,
        application=application,
        server_module=server_module,
        server_args=server_args,
        command_hint=command_hint,
        confidence=confidence,
    )