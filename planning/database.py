import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from .course_markdown import remove_legacy_course_metadata
from .course_storage import CourseStorageError, synchronize_course_files


DATABASE_NAME = "planning.sqlite3"
APPLICATION_ID = 0x54454D50
WORKSPACE_RECORDS = ("carers", "day_notes", "events", "notes", "tasks")
WORKSPACE_TABLES = ("settings", "weekend_switches", "day_overrides", "app_preferences", *WORKSPACE_RECORDS)
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
    (
        "CREATE TABLE workspaces (id INTEGER PRIMARY KEY, share_code TEXT UNIQUE)",
        "INSERT INTO workspaces(id) VALUES (0)",
        """CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL, username_key TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            own_workspace INTEGER NOT NULL UNIQUE REFERENCES workspaces(id),
            joined_workspace INTEGER REFERENCES workspaces(id)
        )""",
        "CREATE INDEX accounts_by_joined_workspace ON accounts(joined_workspace)",
        """CREATE TABLE account_logins (
            token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        )""",
        "CREATE INDEX account_logins_by_expiry ON account_logins(expires_at)",
        "ALTER TABLE settings RENAME TO previous_settings",
        """CREATE TABLE settings (
            workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id),
            name_a TEXT NOT NULL, color_a TEXT NOT NULL,
            name_b TEXT NOT NULL, color_b TEXT NOT NULL,
            anchor TEXT NOT NULL, first_parent INTEGER NOT NULL CHECK (first_parent IN (1, 2)),
            timezone TEXT NOT NULL
        )""",
        """INSERT INTO settings SELECT 0, name_a, color_a, name_b, color_b, anchor, first_parent, timezone
           FROM previous_settings""",
        "DROP TABLE previous_settings",
        "ALTER TABLE weekend_switches RENAME TO previous_weekend_switches",
        """CREATE TABLE weekend_switches (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            year INTEGER NOT NULL CHECK (year BETWEEN 1 AND 9999), PRIMARY KEY (workspace_id, year)
        )""",
        "INSERT INTO weekend_switches SELECT 0, year FROM previous_weekend_switches",
        "DROP TABLE previous_weekend_switches",
        "ALTER TABLE day_overrides RENAME TO previous_day_overrides",
        """CREATE TABLE day_overrides (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            day TEXT NOT NULL, parent INTEGER NOT NULL CHECK (parent IN (1, 2)), PRIMARY KEY (workspace_id, day)
        )""",
        "INSERT INTO day_overrides SELECT 0, day, parent FROM previous_day_overrides",
        "DROP TABLE previous_day_overrides",
        "ALTER TABLE app_preferences RENAME TO previous_app_preferences",
        """CREATE TABLE app_preferences (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (workspace_id, key)
        )""",
        "INSERT INTO app_preferences SELECT 0, key, value FROM previous_app_preferences",
        "DROP TABLE previous_app_preferences",
        *(f"ALTER TABLE {table} ADD COLUMN workspace_id INTEGER REFERENCES workspaces(id)" for table in WORKSPACE_RECORDS),
        *(f"UPDATE {table} SET workspace_id = 0" for table in WORKSPACE_RECORDS),
        "CREATE INDEX carers_by_workspace ON carers(workspace_id)",
        "DROP INDEX day_notes_by_day",
        "CREATE INDEX day_notes_by_day ON day_notes(workspace_id, day, id)",
        "DROP INDEX events_by_day",
        "CREATE INDEX events_by_day ON events(workspace_id, day, start_time, id)",
        "DROP INDEX events_due",
        "CREATE INDEX events_due ON events(workspace_id, remind_at) WHERE remind_at IS NOT NULL",
        "CREATE INDEX notes_by_workspace ON notes(workspace_id, updated_at DESC, id DESC)",
        "CREATE INDEX tasks_by_workspace ON tasks(workspace_id)",
    ),
    (
        "ALTER TABLE courses ADD COLUMN theme TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE courses ADD COLUMN level TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE courses ADD COLUMN difficulty TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE courses ADD COLUMN added_at TEXT NOT NULL DEFAULT ''",
        "UPDATE courses SET added_at = updated_at",
    ),
    ("ALTER TABLE accounts ADD COLUMN site_name TEXT NOT NULL DEFAULT ''",),
    (remove_legacy_course_metadata,),
    (
        "ALTER TABLE visitors ADD COLUMN account_id INTEGER REFERENCES accounts(id)",
        "CREATE INDEX visitors_by_account ON visitors(account_id)",
    ),
)


def connect(path, *, read_only=False):
    target = path.as_uri() + "?mode=ro" if read_only else path
    connection = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction(path, *, write=False, course_files=False):
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        with connection:
            yield connection
            if course_files:
                try:
                    synchronize_course_files(connection, path.parent / "cours")
                except OSError as error:
                    raise CourseStorageError("Le dossier des cours est inaccessible.") from error


def private_file(path):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"):
        pass


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        private_file(path)
    except FileExistsError:
        pass

    with transaction(path, write=True, course_files=True) as connection:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if application_id == 0 and version == 0:
            if connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone():
                raise ValueError(f"{path} n’est pas une base Planneli.")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        elif application_id != APPLICATION_ID:
            raise ValueError(f"{path} n’est pas une base Planneli.")
        if version > len(MIGRATIONS):
            raise ValueError(f"{path} nécessite une version plus récente de Planneli.")
        for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            for statement in migration:
                if callable(statement):
                    statement(connection)
                else:
                    connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {number}")


def validate_backup(connection, path):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    if application_id != APPLICATION_ID or not 1 <= version <= len(MIGRATIONS):
        raise ValueError(f"{path} n’est pas une base Planneli compatible.")
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
