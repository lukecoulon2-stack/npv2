import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path


DATABASE_NAME = "planning.sqlite3"
APPLICATION_ID = 0x54454D50
MIGRATIONS = (
    (
        """CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name_a TEXT NOT NULL, color_a TEXT NOT NULL,
            name_b TEXT NOT NULL, color_b TEXT NOT NULL,
            anchor TEXT NOT NULL, first_parent INTEGER NOT NULL CHECK (first_parent IN (1, 2)),
            timezone TEXT NOT NULL
        )""",
        """CREATE TABLE weekend_switches (
            year INTEGER PRIMARY KEY CHECK (year BETWEEN 1 AND 9999)
        )""",
        """CREATE TABLE day_overrides (
            day TEXT PRIMARY KEY,
            parent INTEGER NOT NULL CHECK (parent IN (1, 2))
        )""",
        """CREATE TABLE carers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1))
        )""",
        """CREATE TABLE carer_days (
            carer_id INTEGER NOT NULL REFERENCES carers(id) ON DELETE CASCADE,
            weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            PRIMARY KEY (carer_id, weekday)
        )""",
        """CREATE TABLE day_notes (
            id INTEGER PRIMARY KEY,
            day TEXT NOT NULL, author TEXT NOT NULL, content TEXT NOT NULL,
            checked INTEGER CHECK (checked IN (0, 1))
        )""",
        "CREATE INDEX day_notes_by_day ON day_notes(day, id)",
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, day TEXT NOT NULL, start_time TEXT, end_time TEXT,
            location TEXT NOT NULL, note TEXT NOT NULL, color TEXT NOT NULL,
            reminder_minutes INTEGER CHECK (reminder_minutes >= 0), remind_at INTEGER
        )""",
        "CREATE INDEX events_by_day ON events(day, start_time, id)",
        """CREATE TABLE notes (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL, content TEXT NOT NULL,
            day TEXT, people TEXT NOT NULL, location TEXT NOT NULL, color TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
    ),
    (
        """CREATE TABLE reminder_receipts (
            client TEXT NOT NULL,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            remind_at INTEGER NOT NULL,
            PRIMARY KEY (client, event_id, remind_at)
        )""",
        "CREATE INDEX events_due ON events(remind_at) WHERE remind_at IS NOT NULL",
    ),
    (
        """CREATE TABLE visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            device TEXT NOT NULL,
            UNIQUE (ip, device)
        )""",
        """CREATE TABLE connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id INTEGER NOT NULL REFERENCES visitors(id),
            connected_at TEXT NOT NULL
        )""",
    ),
    ("CREATE INDEX connections_by_visitor ON connections(visitor_id, id DESC)",),
    ("CREATE TABLE app_preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)",),
    (
        """CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL,
            due TEXT, created_at TEXT NOT NULL, completed_at TEXT
        )""",
        """CREATE TABLE task_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            filename TEXT NOT NULL, mime TEXT NOT NULL, digest TEXT NOT NULL, image BLOB NOT NULL,
            UNIQUE(task_id, digest)
        )""",
        """CREATE TABLE subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE
        )""",
        """CREATE TABLE courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            title TEXT NOT NULL, markdown TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX courses_by_subject ON courses(subject_id, updated_at DESC)",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL",
        "CREATE INDEX tasks_by_course ON tasks(course_id)",
        *(f"ALTER TABLE {table} ADD COLUMN deleted_at TEXT" for table in ("notes", "events", "tasks", "courses")),
    ),
)


def connect(path, *, read_only=False):
    target = path.as_uri() + "?mode=ro" if read_only else path
    connection = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction(path, *, write=False):
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        with connection:
            yield connection


def private_file(path):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"):
        pass


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        private_file(path)
    except FileExistsError:
        pass

    with transaction(path, write=True) as connection:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if application_id == 0 and version == 0:
            if connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone():
                raise ValueError(f"{path} n’est pas une base Naoning.")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        elif application_id != APPLICATION_ID:
            raise ValueError(f"{path} n’est pas une base Naoning.")
        if version > len(MIGRATIONS):
            raise ValueError(f"{path} nécessite une version plus récente de Naoning.")
        for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            for statement in migration:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {number}")


def validate_backup(connection, path):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    if application_id != APPLICATION_ID or not 1 <= version <= len(MIGRATIONS):
        raise ValueError(f"{path} n’est pas une base Naoning compatible.")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError(f"{path} est endommagée.")


def backup(source, target):
    if not source.is_file():
        raise ValueError(f"Aucune base à sauvegarder dans {source}.")
    with closing(connect(source, read_only=True)) as input_db:
        validate_backup(input_db, source)
        private_file(target)
        try:
            with closing(connect(target)) as output_db:
                input_db.backup(output_db)
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def restore(source, target):
    if target.exists() and source.is_file() and source.samefile(target):
        raise ValueError("Choisir un fichier de sauvegarde différent de la base active.")
    if not source.is_file():
        raise ValueError(f"Sauvegarde introuvable dans {source}.")
    previous = None
    with closing(connect(source, read_only=True)) as input_db:
        validate_backup(input_db, source)
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            previous = target.with_name(f"avant-restauration-{stamp}.sqlite3")
            backup(target, previous)
        else:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_file(target)
        with closing(connect(target)) as output_db:
            input_db.backup(output_db)
    initialize(target)
    return previous
