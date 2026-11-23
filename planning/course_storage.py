import json
import os
import re
from tempfile import TemporaryDirectory


class CourseStorageError(OSError):
    pass


def stage_if_changed(directory, path, text):
    content = text.encode("utf-8")
    try:
        if path.read_bytes() == content:
            return
    except FileNotFoundError:
        pass

    temporary = directory / path.name
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        output.write(content)


def synchronize_course_files(connection, directory):
    directory.mkdir(mode=0o700, exist_ok=True)
    catalog = {}
    with TemporaryDirectory(dir=directory, prefix=".catalog-") as temporary:
        staging = directory / os.path.basename(temporary)
        for row in connection.execute(
            """SELECT courses.*, subjects.name AS subject FROM courses
               JOIN subjects ON subjects.id = courses.subject_id ORDER BY courses.id""",
        ):
            filename = f"{row['id']}.md"
            stage_if_changed(staging, directory / filename, row["markdown"])
            catalog[str(row["id"])] = {
                "id": row["id"], "fichier": filename, "nom": row["title"], "matiere": row["subject"],
                "theme": row["theme"] or None, "niveau": row["level"] or None, "date_ajout": row["added_at"],
                "difficulte": row["difficulty"] or None, "supprime_le": row["deleted_at"],
            }
        stage_if_changed(staging, directory / "index.json", json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        for file in sorted(staging.iterdir()):
            os.replace(file, directory / file.name)
    for file in directory.glob("*.md"):
        if re.fullmatch(r"[1-9][0-9]*", file.stem) and file.stem not in catalog:
            if file.is_symlink() or file.is_file():
                file.unlink(missing_ok=True)
