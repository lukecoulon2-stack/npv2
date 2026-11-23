import unicodedata

from flask import Blueprint, g, jsonify, request

from .accounts import account_transaction
from .rules import InputError, now_iso


COLLECTIONS = {
    "notes": "title || ' ' || content || ' ' || people || ' ' || location",
    "events": "title || ' ' || note || ' ' || location",
    "tasks": "title || ' ' || content",
    "courses": ("title || ' ' || theme || ' ' || level || ' ' || difficulty || ' ' || markdown || ' ' "
                "|| (SELECT name FROM subjects WHERE id = subject_id)"),
}


def move_to_trash(connection, collection, identifier):
    scope = " AND workspace_id = ?" if collection != "courses" else ""
    parameters = (g.workspace,) if scope else ()
    return connection.execute(
        f"UPDATE {collection} SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL{scope}",
        (now_iso(), identifier, *parameters),
    )


def fold(text):
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def organizer_routes(database):
    blueprint = Blueprint("organizer", __name__, url_prefix="/api")

    @blueprint.get("/search")
    def search():
        query = fold(request.args.get("q", "").strip()).strip()
        scope = request.args.get("type", "")
        if scope and scope not in COLLECTIONS:
            raise InputError("Rubrique inconnue.")
        if not query or len(query) > 120:
            return jsonify([])
        tables = [scope] if scope else COLLECTIONS
        filters = " AND ".join("instr(fold(search_text), ?) > 0" for _ in query.split())
        sources = " UNION ALL ".join(
            f"SELECT '{table}' AS kind, id, title, {COLLECTIONS[table]} AS search_text "
            f"FROM {table} WHERE deleted_at IS NULL"
            + (" AND workspace_id = ?" if table != "courses" else "")
            for table in tables
        )
        workspaces = [g.workspace for table in tables if table != "courses"]
        with account_transaction(database) as connection:
            connection.create_function("fold", 1, fold, deterministic=True)
            rows = connection.execute(
                f"""SELECT kind, id, title FROM ({sources}) WHERE {filters}
                    ORDER BY instr(fold(title), ?) = 0, fold(title), id LIMIT 50""",
                (*workspaces, *query.split(), query),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/trash")
    def trash():
        sources = " UNION ALL ".join(
            f"SELECT '{table}' AS kind, id, title, deleted_at FROM {table} WHERE deleted_at IS NOT NULL"
            + (" AND workspace_id = ?" if table != "courses" else "")
            for table in COLLECTIONS
        )
        workspaces = [g.workspace for table in COLLECTIONS if table != "courses"]
        with account_transaction(database) as connection:
            rows = connection.execute(sources + " ORDER BY deleted_at DESC, id DESC", workspaces).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.post("/trash/<kind>/<int:identifier>")
    @blueprint.delete("/trash/<kind>/<int:identifier>")
    def change_trash(kind, identifier):
        if kind not in COLLECTIONS or not 0 < identifier <= 2**63 - 1:
            raise InputError("Élément introuvable dans la corbeille.", 404)
        command = "DELETE FROM" if request.method == "DELETE" else "UPDATE"
        table = kind if request.method == "DELETE" else f"{kind} SET deleted_at = NULL"
        scope = " AND workspace_id = ?" if kind != "courses" else ""
        parameters = (g.workspace,) if scope else ()
        with account_transaction(database, write=True, course_files=kind == "courses") as connection:
            result = connection.execute(
                f"{command} {table} WHERE id = ? AND deleted_at IS NOT NULL{scope}", (identifier, *parameters),
            )
            if result.rowcount == 0:
                raise InputError("Élément introuvable dans la corbeille.", 404)
        return "", 204

    return blueprint
