"""Diagnostics lisibles, conseils pare-feu et aides réseau pour le journal."""


def explain_error(exc):
    """Retourne (nom du problème, solution courte) pour les erreurs connues."""
    text = str(exc or "").lower()
    errno = getattr(exc, "errno", None)

    if errno == 98 or "address already in use" in text or "only one usage" in text:
        return (
            "PORT DÉJÀ UTILISÉ",
            "Fermez le programme qui utilise ce port ou choisissez un autre port dans la configuration."
        )
    if errno in (13, 1) or "permission denied" in text or "permissionerror" in text:
        return (
            "PERMISSION REFUSÉE",
            "Utilisez un port autorisé (supérieur à 1024) et vérifiez les droits du dossier."
        )
    if "connection refused" in text or "failed to establish a new connection" in text:
        return (
            "SERVEUR INJOIGNABLE",
            "Vérifiez que l'application écoute bien sur le port serveur configuré et qu'elle n'a pas quitté."
        )
    if "no such file or directory" in text or "file not found" in text:
        return (
            "FICHIER INTROUVABLE",
            "Vérifiez le chemin du projet, du serveur ou du fichier de dépendances."
        )
    if "modulenotfounderror" in text or "no module named" in text:
        return (
            "DÉPENDANCE PYTHON MANQUANTE",
            "Relancez l'installation des dépendances dans le venv ou ajoutez le module à requirements.txt."
        )
    if "pip" in text and ("could not find a version" in text or "no matching distribution" in text):
        return (
            "DÉPENDANCE PYTHON INCOMPATIBLE",
            "Vérifiez la version de Python et la version du paquet demandée dans requirements.txt."
        )
    if "timed out" in text or "timeout" in text:
        return (
            "DÉLAI D'ATTENTE DÉPASSÉ",
            "Vérifiez que l'application démarre correctement et augmentez le délai si elle démarre lentement."
        )
    if "address family" in text or "name or service not known" in text:
        return (
            "ADRESSE RÉSEAU INVALIDE",
            "Vérifiez l'adresse d'écoute et utilisez 127.0.0.1 pour le serveur ou 0.0.0.0 pour le proxy."
        )
    if "jsondecodeerror" in text or "expecting value" in text:
        return (
            "CONFIGURATION INVALIDE",
            "Vérifiez le fichier web_deploy_config.json ou recréez la configuration."
        )
    return None


def log_known_error(log, exc, context=""):
    """Écrit une erreur technique puis son diagnostic lisible."""
    diagnostic = explain_error(exc)
    if not diagnostic:
        return False
    problem, solution = diagnostic
    prefix = f" ({context})" if context else ""
    log(f"[ERREUR] {problem}{prefix}")
    log(f"[SOLUTION] {solution}")
    return True


def log_firewall_advice(log, public_port):
    """Affiche les commandes utiles pour autoriser le port public du PC.

    Ces commandes sont volontairement proposées mais jamais exécutées automatiquement.
    """
    public_port = int(public_port)
    log(
        "[INFO] Le kit teste l'accès TCP/HTTP local, mais ne peut pas confirmer "
        "depuis ce PC si le pare-feu autorise les connexions externes."
    )
    log("[INFO] Les commandes ci-dessous sont des conseils ; aucune règle ne sera modifiée par le kit.")
    log("[CONSEIL RÉSEAU] Le serveur local fonctionne, mais l'accès public peut être bloqué par le pare-feu du PC.")
    if __import__("os").name == "nt":
        log(f"[WINDOWS] PowerShell (administrateur) : New-NetFirewallRule -DisplayName \"Web Deployer {public_port}\" -Direction Inbound -Protocol TCP -LocalPort {public_port} -Action Allow")
        log(f"[WINDOWS] Alternative CMD (administrateur) : netsh advfirewall firewall add rule name=\"Web Deployer {public_port}\" dir=in action=allow protocol=TCP localport={public_port}")
        log("[WINDOWS] Vérifiez aussi que le profil Réseau (Privé/Public) autorise cette règle.")
    else:
        log(f"[LINUX/UFW] Si UFW est utilisé : sudo ufw allow {public_port}/tcp && sudo ufw status")
        log(f"[LINUX/firewalld] Si firewalld est utilisé : sudo firewall-cmd --permanent --add-port={public_port}/tcp && sudo firewall-cmd --reload")
        log(f"[LINUX/nftables] Vérifiez vos règles nftables/iptables si UFW/firewalld ne sont pas utilisés.")
    log(f"[ROUTEUR] Redirigez le port WAN TCP {public_port} vers IP_LOCALE_DU_PC:{public_port}.")
    log("[ROUTEUR] Si le test local fonctionne mais pas l'IP publique, vérifiez NAT/port forwarding et un éventuel CGNAT.")
