from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo

from flask import g, request

from .config import DEFAULT_ZONE


PAGES = {
    "/": "Accueil", "/planning": "Planning", "/evenements": "Agenda", "/notes": "Notes",
    "/a-faire": "À faire", "/cours": "Cours", "/jeux": "Mini-jeux", "/reglages": "Réglages",
}

ACTIONS = {
    "accounts.register": "Création de compte et connexion",
    "accounts.login": "Connexion",
    "accounts.logout": "Déconnexion",
    "accounts.share": "Création de session",
    "accounts.join": "Rejoint une session",
    "accounts.leave": "Quitte une session",
    "accounts.rename_site": "Modification du nom affiché",
    "preview_assignment": "Aperçu d’une attribution",
    "apply_assignment": "Modification du planning",
    "get_event": "Consultation d’un événement",
    "library.task": "Consultation d’une tâche",
    "library.course": "Consultation d’un cours",
    "library.import_course": "Lecture du fichier de cours",
    "library.download_course": "Téléchargement d’un cours",
    "library.complete_task": "Modification du statut d’une tâche",
    "maintenance.unlock": "Déverrouillage de la maintenance",
    "maintenance.lock": "Verrouillage de la maintenance",
    "maintenance.account_details": "Consultation des identifiants d’un compte",
    "maintenance.update": "Vérification des mises à jour",
}

OBJECTS = {
    "create_settings": "réglages du planning", "update_settings": "réglages du planning",
    "update_weekend": "inversion des week-ends", "save_carer": "personne de garde",
    "delete_carer": "personne de garde", "create_day_note": "note du jour",
    "update_day_note": "note du jour", "toggle_day_note": "case d’une note du jour",
    "delete_day_note": "note du jour", "save_event": "événement", "delete_event": "événement",
    "save_note": "note", "delete_note": "note", "library.save_task": "tâche",
    "library.delete_task": "tâche", "library.delete_photo": "photo de tâche",
    "library.save_subject": "matière", "library.save_course": "cours", "library.delete_course": "cours",
    "maintenance.clear_data": "données de l’espace", "maintenance.delete_visitor": "historique de visite",
    "maintenance.delete_account": "compte",
}

VERBS = {"POST": "Création", "PUT": "Modification", "PATCH": "Modification", "DELETE": "Suppression"}
LOG_ZONE = ZoneInfo(DEFAULT_ZONE)
output_lock = Lock()


def log_activity(response):
    if request.method in {"HEAD", "OPTIONS"} or "prefetch" in request.headers.get("Sec-Purpose", ""):
        return
    endpoint = request.endpoint
    action = g.get("activity_action") or ACTIONS.get(endpoint)
    if endpoint == "organizer.change_trash":
        action = "Restauration depuis la corbeille" if request.method == "POST" else "Suppression définitive"
    if action is None and endpoint in OBJECTS and request.method in VERBS:
        action = f"{VERBS[request.method]} · {OBJECTS[endpoint]}"
    if action is None:
        return

    parameters = request.view_args or {}
    if endpoint == "maintenance.delete_visitor":
        parameters = {"visitor_id": parameters.get("visitor_id")}
    identifiers = [str(value) for value in parameters.values() if type(value) is int]
    if identifiers:
        action += f" #{identifiers[0]}"
    if response.status_code >= 400:
        action += f" · Échec ({response.status_code})"
    account = g.get("account")
    user_id = g.get("activity_user_id", account["id"] if account is not None else "-")
    stamp = datetime.now(LOG_ZONE).strftime("%H:%M:%S")
    with output_lock:
        print(f"{user_id} {stamp} {action}", flush=True)
