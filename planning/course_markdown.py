import re
import unicodedata


FIELD_NAMES = {
    "matiere": "subject", "cours": "title", "nom": "title", "titre": "title", "nom du cours": "title",
    "niveau": "level", "niveau scolaire": "level", "theme": "theme", "difficulte": "difficulty",
}
COURSE_FIELDS = (("theme", "Thème", 120), ("level", "Niveau", 80), ("difficulty", "Difficulté", 80))
FIELD = re.compile(
    r"(?<!\S)[*_`]*(mati[eè]re|nom\s+du\s+cours|cours|nom|titre|niveau(?:\s+scolaire)?|th[eè]me|difficult[eé])"
    r"[\s*_`]*:[*_`]*[ \t]*", re.IGNORECASE,
)
HEADER = re.compile(
    r"^ {0,3}(?:>[ \t]*)?(?:#{1,6}\s+)?(?:[-–—]+\s*)?[*_`]*(?:infos?|informations?)\s+sur\s+le\s+cours\b"
    r"[\s*_`]*:?[\s*_`]*(.*?)\s*$", re.IGNORECASE,
)
SEPARATOR = re.compile(r"[-–—]{2,}")
FENCE = re.compile(r"^ {0,3}(?:>[ \t]*)?(`{3,}|~{3,})(.*)$")


def metadata_fields(line):
    content = re.sub(r"^\s*(?:>\s*)?(?:[-+*]\s+)?", "", unicodedata.normalize("NFC", line.strip()))
    matches = list(FIELD.finditer(content))
    if not matches or matches[0].start():
        return {}
    fields = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        label = " ".join(match[1].lower().split()).translate(str.maketrans("èé", "ee"))
        value = content[match.end():end].strip().strip("*_`").strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1].strip()
        fields.setdefault(FIELD_NAMES[label], value)
    return fields


def read_metadata_lines(lines, start, fields):
    end = start
    for index in range(start, len(lines)):
        line = lines[index].strip()
        if not line:
            continue
        if SEPARATOR.fullmatch(line):
            return index + 1
        values = metadata_fields(line)
        if not values or fields.keys() & values.keys():
            break
        fields.update(values)
        end = index + 1
    return end


def course_metadata(fields):
    return {name: value for name, value in fields.items() if value and not re.fullmatch(r"<.+>", value)}


def without_block(lines, start, end):
    before = "".join(lines[:start])
    after = "".join(lines[end:])
    return before + after if before.strip() else after.lstrip("\r\n")


def split_course_markdown(markdown):
    lines = markdown.splitlines(keepends=True)
    fence = ""
    for index, line in enumerate(lines):
        text = line.rstrip("\r\n").lstrip("\ufeff")
        marker = FENCE.match(text)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = ""
            continue
        if marker:
            fence = marker[1]
            continue
        header = HEADER.match(text)
        if not header:
            continue
        inline = header[1].strip().removesuffix("--").rstrip().rstrip("#").rstrip()
        fields = metadata_fields(inline)
        if inline and not fields:
            continue
        end = index + 1 if header[1].strip().endswith("--") and fields else read_metadata_lines(lines, index + 1, fields)
        if fields:
            return course_metadata(fields), without_block(lines, index, end)

    first = next((index for index, line in enumerate(lines) if line.strip()), len(lines))
    if first == len(lines):
        return {}, markdown
    if lines[first].strip().lstrip("\ufeff") == "---":
        fields = {}
        unrelated = False
        for index in range(first + 1, len(lines)):
            line = lines[index].strip()
            if line == "---":
                body = without_block(lines, first, index + 1) if fields and not unrelated else markdown
                return course_metadata(fields), body
            values = metadata_fields(line)
            unrelated = unrelated or (bool(line) and not values)
            fields.update(values)
        return {}, markdown
    fields = {}
    end = read_metadata_lines(lines, first, fields)
    if len(fields) >= 2 and fields.keys() & {"subject", "title"}:
        return course_metadata(fields), without_block(lines, first, end)
    return course_metadata(fields), markdown


def remove_legacy_course_metadata(connection):
    rows = connection.execute("SELECT id, markdown, theme, level, difficulty FROM courses").fetchall()
    for row in rows:
        metadata, content = split_course_markdown(row["markdown"])
        if content != row["markdown"]:
            values = tuple(
                row[name] or (metadata.get(name, "") if len(metadata.get(name, "")) <= length else "")
                for name, _, length in COURSE_FIELDS
            )
            connection.execute(
                "UPDATE courses SET markdown = ?, theme = ?, level = ?, difficulty = ? WHERE id = ?",
                (content, *values, row["id"]),
            )
