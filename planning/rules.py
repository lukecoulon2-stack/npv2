import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import DEFAULT_ZONE


class InputError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text_value(data, key, label, *, length, required=False, multiline=False):
    original = data.get(key, "")
    if not isinstance(original, str):
        raise InputError(f"« {label} » doit être un texte.")
    value = original if multiline else original.strip()
    if required and not value.strip():
        raise InputError(f"Renseignez « {label} ».")
    if len(value) > length:
        raise InputError(f"« {label} » est limité à {length} caractères.")
    return value


def civil_day(value, label="Date"):
    if isinstance(value, str):
        try:
            result = date.fromisoformat(value)
            if result.isoformat() == value:
                return result
        except ValueError:
            pass
    raise InputError(f"« {label} » doit être une date valide.")


def dates_between(first, last):
    start = first.toordinal()
    return map(date.fromordinal, range(start, last.toordinal() + 1))


def calendar_range(args):
    first = civil_day(args.get("start"), "Début")
    last = civil_day(args.get("end"), "Fin")
    if not 0 <= (last - first).days < 366:
        raise InputError("Choisissez une plage de calendrier d’un an maximum.")
    return first, last


def color_value(data, key, label="Couleur"):
    value = data.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise InputError(f"« {label} » doit être une couleur hexadécimale.")
    return value.lower()


def boolean_value(data, key, label):
    value = data.get(key)
    if type(value) is not bool:
        raise InputError(f"« {label} » doit être activé ou désactivé.")
    return value


def parent_value(value):
    if type(value) is not int or value not in (1, 2):
        raise InputError("Choisissez l’un des deux parents.")
    return value


def timezone_value(value):
    if not isinstance(value, str) or len(value) > 80:
        raise InputError("Indiquez un fuseau horaire IANA, par exemple Europe/Paris.")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise InputError("Indiquez un fuseau horaire IANA, par exemple Europe/Paris.") from None


def settings_row(connection, *, required=False):
    row = connection.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    if required and row is None:
        raise InputError("Configurez d’abord les deux parents dans Mon planning.", 409)
    return row


def timezone_for(connection, settings):
    if settings is not None:
        return ZoneInfo(settings["timezone"])
    previous = connection.execute("SELECT value FROM app_preferences WHERE key = 'timezone'").fetchone()
    return ZoneInfo(previous["value"] if previous else DEFAULT_ZONE)


def settings_fields(data):
    return (
        text_value(data, "name_a", "Parent 1", length=50, required=True),
        color_value(data, "color_a", "Couleur du parent 1"),
        text_value(data, "name_b", "Parent 2", length=50, required=True),
        color_value(data, "color_b", "Couleur du parent 2"),
        timezone_value(data.get("timezone", DEFAULT_ZONE)).key,
    )


class CustodyCalendar:
    def __init__(self, connection, first, last):
        settings = settings_row(connection, required=True)
        self.anchor = date.fromisoformat(settings["anchor"])
        self.first_parent = settings["first_parent"]
        self.names = [settings["name_a"], settings["name_b"]]
        self.weekend_years = {
            row["year"]
            for row in connection.execute(
                "SELECT year FROM weekend_switches WHERE year BETWEEN ? AND ?", (first.year, last.year)
            )
        }
        self.overrides = {
            row["day"]: row["parent"]
            for row in connection.execute(
                "SELECT day, parent FROM day_overrides WHERE day BETWEEN ? AND ?",
                (first.isoformat(), last.isoformat()),
            )
        }

    def regular_parent(self, day):
        weeks = (day - self.anchor).days // 7
        flip_weekend = day.weekday() >= 5 and day.year in self.weekend_years
        flipped = bool(weeks % 2) ^ flip_weekend
        return 3 - self.first_parent if flipped else self.first_parent

    def parent(self, day):
        assigned = self.overrides.get(day.isoformat())
        return self.regular_parent(day) if assigned is None else assigned


@dataclass(frozen=True)
class Period:
    first: date
    last: date
    action: str
    target: int | None

    @classmethod
    def from_json(cls, data):
        first = civil_day(data.get("start"), "Début")
        last = civil_day(data.get("end"), "Fin")
        if last < first:
            raise InputError("La fin doit être le même jour que le début ou après.")
        action = data.get("action")
        if action not in ("assign", "invert", "clear"):
            raise InputError("Choisissez une modification du planning.")
        return cls(first, last, action, parent_value(data.get("parent")) if action == "assign" else None)

    def changes(self, calendar):
        for day in dates_between(self.first, self.last):
            before = calendar.parent(day)
            if self.action == "assign":
                after = self.target
            elif self.action == "invert":
                after = 3 - before
            else:
                after = calendar.regular_parent(day)
            yield day.isoformat(), before, after

    def preview(self, calendar):
        digest = hashlib.sha256(json.dumps([
            self.first.isoformat(), self.last.isoformat(), self.action, self.target, calendar.names,
        ]).encode())
        counts = {1: 0, 2: 0}
        sample = []
        for index, (day, before, after) in enumerate(self.changes(calendar)):
            digest.update(f"{day}:{before}:{after}:{day in calendar.overrides}".encode())
            counts[after] += 1
            if index < 7:
                sample.append({"day": day, "before": before, "after": after})
        return {"token": digest.hexdigest(), "counts": counts, "sample": sample}

    def apply(self, connection, calendar):
        if self.action == "clear":
            connection.execute(
                "DELETE FROM day_overrides WHERE day BETWEEN ? AND ?",
                (self.first.isoformat(), self.last.isoformat()),
            )
        else:
            connection.executemany(
                """INSERT INTO day_overrides(day, parent) VALUES (?, ?)
                   ON CONFLICT(day) DO UPDATE SET parent = excluded.parent""",
                ((day, after) for day, _, after in self.changes(calendar)),
            )


def time_value(value, label):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise InputError(f"« {label} » doit être une heure valide.")
    return value


def reminder_timestamp(day, start, minutes, zone):
    if minutes is None:
        return None
    local = datetime.combine(day, time.fromisoformat(start or "09:00"), tzinfo=zone)
    # Python chooses the first occurrence of a repeated hour and moves a skipped hour forward.
    return int(local.timestamp()) - minutes * 60


def event_fields(data, zone):
    day = civil_day(data.get("day"))
    start = time_value(data.get("start_time"), "Heure de début")
    end = time_value(data.get("end_time"), "Heure de fin")
    if end and (start is None or end <= start):
        raise InputError("L’heure de fin doit être après l’heure de début, le même jour.")
    reminder = data.get("reminder_minutes")
    if reminder is not None and (type(reminder) is not int or not 0 <= reminder <= 10080):
        raise InputError("Le délai du rappel doit être compris entre 0 et 10 080 minutes.")
    return (
        text_value(data, "title", "Titre", length=120, required=True),
        day.isoformat(), start, end,
        text_value(data, "location", "Lieu", length=200),
        text_value(data, "note", "Note", length=16000, multiline=True),
        color_value(data, "color"), reminder, reminder_timestamp(day, start, reminder, zone),
    )


def refresh_reminder_times(connection, zone):
    rows = connection.execute(
        "SELECT id, day, start_time, reminder_minutes FROM events WHERE reminder_minutes IS NOT NULL"
    ).fetchall()
    connection.executemany(
        "UPDATE events SET remind_at = ? WHERE id = ?",
        (
            (reminder_timestamp(date.fromisoformat(row["day"]), row["start_time"], row["reminder_minutes"], zone),
             row["id"])
            for row in rows
        ),
    )


def now_iso():
    return datetime.now(timezone.utc).isoformat()
