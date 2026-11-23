# Planneli — Planning familial

Planneli réunit l’alternance parentale, les rendez-vous et le bloc-notes de la famille. Chaque compte dispose de son espace personnel dans la base SQLite de l’ordinateur qui héberge l’application.

## Consignes pour les assistants IA

Avant de terminer une intervention, les assistants IA doivent inscrire dans la liste `files` de [new.json](new.json) le chemin relatif de chaque fichier créé ou modifié, y compris la documentation, les tests et le manifeste lui-même. Chaque chemin doit apparaître une seule fois. Conservez les entrées qui correspondent aux changements en attente de publication.

## Lancer Planneli

Avec Python 3.10 ou une version plus récente, lancer depuis le dossier du projet.

```bash
python3 start.py
```

Le premier lancement crée l’environnement virtuel du projet, installe les dépendances avec pip et initialise la base. Une connexion Internet est nécessaire pour télécharger les dépendances au premier lancement. Sur les distributions Linux qui séparent `venv` du paquet Python, installer également le paquet système correspondant.

Le terminal affiche l’adresse du site, à ouvrir dans le navigateur. Créez un compte avec un nom d’utilisateur et un mot de passe d’au moins huit caractères. Le navigateur conserve la connexion pendant 30 jours via un cookie. Pour accéder au site, créez une session ou rejoignez-en une. Sur l’accueil, choisissez **Configurer le planning** pour saisir les deux parents et la semaine de départ. Planneli prend le lundi de cette semaine comme référence. Arrêtez le serveur avec **Ctrl+C**.

### Partager un espace

Choisissez **Créer une session** pour obtenir un code de connexion à huit caractères, également visible dans **Réglages → Compte → Session**. Une autre personne peut le saisir dans **Rejoindre une session** depuis son propre compte, sur la même instance de Planneli. Les invités peuvent consulter et modifier le planning, les événements, les notes et les tâches de l’hôte. La session et son code restent actifs. **Quitter la session** ramène un invité à l’écran de choix. Les cours et matières sont communs aux comptes qui ont accès au site.

Dans **Réglages → Compte → Apparence**, **Nom affiché du site** personnalise l’en-tête et le titre de l’onglet pour votre compte. Videz ce champ pour rétablir Planneli. La section **Planning** regroupe les parents et l’alternance, les week-ends et les personnes de garde.

Après une mise à jour depuis une version sans comptes, les anciennes données personnelles sont conservées dans la base. Pour les rattacher, créez un compte puis exécutez cette commande sur l’ordinateur qui héberge Planneli avant de créer sa session.

```bash
python3 start.py --claim-existing NOM_UTILISATEUR
```

Si le serveur utilise un fichier de configuration personnalisé, passez la même option `--config` à cette commande. Les cours existants sont disponibles après avoir créé ou rejoint une session.

### Journal dans le terminal

Le terminal affiche une ligne par chargement de page, connexion ou action enregistrée. La ligne commence par l’ID du compte, puis l’heure de Paris et l’action. Un tiret représente une visite avant connexion.

```text
42 14:32:08 Chargement de page · Notes
42 14:32:15 Création · note
42 14:32:22 Modification · note #7
```

### Modifier le lancement

Modifier [planning_config_starter.json](planning_config_starter.json), puis redémarrer Planneli. Le fichier est lu à côté de `start.py`. Une autre configuration peut être utilisée avec `python3 start.py --config /chemin/config.json`.

| Réglage | Valeur d’exemple | Effet |
| --- | --- | --- |
| `mode` | `"normal"` | `"bench"` utilise une base vide et temporaire. Elle accepte les écritures pendant la session et est supprimée à l’arrêt normal. |
| `host` | `"127.0.0.1"` | Passer à `"0.0.0.0"` pour accéder au site depuis le même réseau Wi-Fi. |
| `port` | `8000` | Port web de Planneli. |
| `data_dir` | `null` | Dossier utilisateur par défaut. Pour changer l’emplacement en mode normal, indiquer un chemin absolu hors du projet. |

Sous Linux, la base se trouve dans `${XDG_DATA_HOME:-$HOME/.local/share}/planning-familial/`. Sous macOS, elle se trouve dans `~/Library/Application Support/planning-familial/`. Sous Windows, elle se trouve dans `%LOCALAPPDATA%\planning-familial\`. La base s’appelle `planning.sqlite3`.

### Accéder depuis le téléphone

Régler `host` à `"0.0.0.0"`, relancer Planneli et ouvrir sur le téléphone l’adresse indiquée après **Sur le même Wi-Fi**. Les deux appareils doivent être sur le même réseau. Utiliser une adresse HTTPS pour chiffrer le mot de passe et le cookie de connexion sur le réseau.

### Rappels et HTTPS

Avec Planneli ouvert, un rappel arrive dans le navigateur qui consulte l’application. En cas de refus ou lorsque les notifications système sont indisponibles, Planneli affiche le rappel dans sa propre interface. Un événement sans horaire prend 9 h comme heure de départ dans le fuseau choisi. Le rappel est signalé une fois par navigateur et par échéance. À la reprise d’une page suspendue ou déconnectée, Planneli récupère les rappels échus depuis moins d’une heure.

Sur le Wi-Fi, ouvrir Planneli via une adresse HTTPS et un certificat approuvé par le téléphone pour utiliser les notifications système. Par exemple, avec Caddy sur la même machine, garder `host` à `"127.0.0.1"` dans le JSON. Dans un fichier Caddyfile local, remplacer l’IP par celle de l’ordinateur et adapter le port en amont au JSON.

```caddyfile
{
    auto_https disable_redirects
}

https://192.168.1.42:8443 {
    tls internal
    reverse_proxy 127.0.0.1:8000
}
```

Démarrer Caddy avec `caddy run --config /chemin/Caddyfile`. Installer et approuver l’autorité locale de Caddy sur les appareils de la famille avant d’ouvrir l’adresse HTTPS. Sur les versions iOS qui prennent en charge cette fonction, ajouter Planneli à l’écran d’accueil et demander les notifications depuis l’application. [HTTPS local de Caddy](https://caddyserver.com/docs/automatic-https#local-https) · [Notifications sur mobile](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API/Using_the_Notifications_API) · [Application web sur iOS et iPadOS](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)

La livraison couvre les rappels avec Planneli ouvert. Les rappels après fermeture nécessitent Web Push, une origine HTTPS approuvée et des essais sur les appareils visés. Les essais sur Safari iOS et Chrome Android physiques restent à faire.

### À faire et Cours

Dans **À faire**, chaque tâche peut avoir des détails et une échéance. Cochez-la pour la terminer et joindre, si besoin, jusqu’à quatre photos JPEG, PNG ou WebP de 3 Mio chacune. Les photos sont conservées dans la base SQLite et incluses dans les sauvegardes.

Les **Cours** sont regroupés par niveau. Les filtres de matière, de thème et de difficulté peuvent être combinés. Les cours dont le niveau est inconnu apparaissent à la fin de la liste.

Dans **Cours → Ajouter un cours**, copiez le prompt, ajoutez le sujet souhaité et transmettez-le à votre IA. Importez le fichier `.md` obtenu en UTF-8. Planneli lit le bloc « Info sur le cours » pour préremplir la fiche, puis retire ce bloc du Markdown publié. Vérifiez les informations détectées, renseignez les champs manquants, puis cliquez sur **Publier le cours**. La matière est créée si besoin. Vous pouvez ensuite lire le cours dans Planneli, le modifier ou télécharger son fichier Markdown.

Le dossier `cours/` à côté de la base contient un fichier `<id>.md` par cours et un `index.json` qui associe chaque identifiant à son nom, sa matière, son thème, son niveau, sa date d’ajout et sa difficulté. Planneli synchronise ces fichiers à partir de SQLite, y compris lors d’une restauration. Pour les cours existants, la migration utilise la dernière date d’enregistrement et conserve les champs inconnus à renseigner lors d’une modification.

Dans une tâche, le menu **Cours à réviser** crée un raccourci vers le cours choisi. La loupe en haut à droite recherche dans les notes, événements, tâches et cours. Les éléments supprimés depuis ces rubriques peuvent être restaurés ou effacés définitivement dans **Réglages → Données → Corbeille**.

### Mini-jeux

Ouvrez **Mini-jeux** depuis l’accueil. **Orbitale** propose des pièces de différentes tailles et des lignes à compléter, **Fusion 243** combine des tuiles sur une grille de 5 × 5 et **Paires flash** fait retrouver six paires. Les jeux se jouent dans Planneli, avec des commandes tactiles ou au clavier.

### Maintenance

Ouvrir **Réglages → Données → Maintenance**. Planneli génère un code de maintenance affiché dans le terminal au démarrage. Pour utiliser un code fixe, définir la variable d’environnement `NAONING_MAINTENANCE_CODE` avant de lancer Planneli. Le menu se verrouille au bout de 15 minutes.

Le journal enregistre les connexions et les ouvertures ou rechargements de page. Chaque identifiant de visite authentifiée correspond à un compte, un navigateur reconnu par cookie et une adresse IP. Les visites antérieures à ce rattachement restent visibles dans le journal. La maintenance affiche les 100 dernières connexions et les données de l’espace actif au format JSON.

Dans **Comptes**, ouvrez un compte pour voir ses identifiants de visite, leur adresse IP et leur dernière connexion. Supprimer un identifiant efface son historique et déclenche l’attribution d’un nouvel identifiant à la prochaine visite. Supprimer le compte révoque ses connexions et efface tous ses identifiants de visite. Si le compte a créé une session partagée, celle-ci reste accessible avec son code.

Dans **Gestion des données**, trois actions distinctes permettent de réinitialiser le planning, de vider le bloc-notes ou d’effacer les événements. Chaque action demande une confirmation. Après réinitialisation du planning, configurer à nouveau les parents et l’alternance. Le fuseau horaire et les rappels des événements sont conservés par cette action.

**Mise à jour** prépare les sources de la branche par défaut du dépôt GitHub avec Git, en mode normal. Redémarrer avec `python3 start.py` pour appliquer une révision préparée. SQLite et le JSON de lancement restent sur le PC. L’installation exige un dépôt contenant le lanceur, les dépendances et l’application. [Dépôt du projet](https://github.com/lukecoulon2-stack/npv2)

### Sauvegarder et restaurer

En mode normal, choisir un fichier de destination qui n’existe pas dans un dossier déjà créé.

```bash
python3 start.py --backup /chemin/tempo-sauvegarde.sqlite3
```

Pour revenir à une sauvegarde, arrêter Planneli, puis lancer la commande de restauration. Planneli conserve une copie datée de la base précédente. Relancer ensuite normalement.

```bash
python3 start.py --restore /chemin/tempo-sauvegarde.sqlite3
```

Les opérations de sauvegarde et de restauration utilisent le `data_dir` de la configuration de lancement. Si le site est habituellement lancé avec `--config`, passer la même option pour ces opérations.

### Vérifications Python

```bash
.venv-planning/bin/python -m unittest discover -s tests -v
```

Sous Windows, utiliser `.venv-planning\Scripts\python.exe`. La feuille de route et l’avancement sont dans [todo.md](todo.md).

<details>
<summary>Illustration de l’accueil</summary>

Le fichier [planning/static/calendrier.webp](planning/static/calendrier.webp) provient de l’outil ImageGen intégré. Le texte ci-dessous a servi à générer le bandeau.

> Use case: stylized-concept. Create the wide background illustration for a premium French family calendar web dashboard, landscape 2:1. A single beautifully designed floating frosted lilac glass calendar plate, with two rounded binder loops and an orderly 5 by 4 array of raised small glass tiles, a few glowing mauve and soft pink tiles, seen at a subtle three-quarter tilt. One lightly frosted pink glass orb near the lower right and delicate wide iridescent violet light ribbons looping behind the calendar, for a sculptural elegant editorial look. Main calendar positioned in the rightmost 45% with space around it. Keep the left 48% as dark, quiet near-black plum (#23103c), slightly hazy and plain, reserved for live HTML text. Rich saturated lilac and plum and soft rose against a consistently dark plum background, directional studio highlights, subtle fine grain, crisp glass edges. Screen print quality, no white backdrop, no hands, no environment, no UI chrome, absolutely no letters, numbers, text, or logos.

</details>

---

# Web Deployer

Kit autonome à copier dans la racine d'un projet Python.

L'application reste exécutée sur le PC de l'utilisateur : Web Deploy Kit expose un
service local et ne déploie pas l'application sur un hébergeur distant.

## Installation

Copiez le dossier `web_deploy/` et le fichier `deploy.py` à la racine du projet.

Lancez :

```bash
python deploy.py
```

Au lancement, choisissez entre la version simple et la version avancée. Chaque interface
permet de sélectionner le fichier Python qui démarre votre serveur. La version simple
regroupe les réglages essentiels du serveur, des ports, du proxy et du venv. La version
avancée ajoute notamment HTTPS, le tunnel Cloudflare, les contrôles d'accès et les
diagnostics réseau.

Dans la version avancée, vous pouvez décocher **Proxy public (Caddy)** pour lancer
l'application en local uniquement. Pour l'exposer sans installer Caddy, sélectionnez
**Accès direct sans Caddy**. Le serveur écoutera alors sur toutes les interfaces et le
kit demandera une confirmation avant le lancement. Ce mode n'inclut ni HTTPS, ni
authentification, ni filtrage réseau par le kit.

Si Caddy est installé, vous pouvez aussi lancer le serveur en local puis utiliser le
bouton **ACTIVER LE PROXY PUBLIC** pour démarrer Caddy sans arrêter le serveur.

## Installation automatique via git

**Windows (CMD) :**

```cmd
git clone https://github.com/LukeCOULON/web_deploy_kit.git "%TEMP%\web_deploy_kit" && xcopy "%TEMP%\web_deploy_kit\*" "." /E /I /Y && rmdir /S /Q "%TEMP%\web_deploy_kit" && python deploy.py
```

**Linux (Terminal) :**

```bash
git clone https://github.com/LukeCOULON/web_deploy_kit.git /tmp/web_deploy_kit && \
cp -rn /tmp/web_deploy_kit/. . && \
rm -rf /tmp/web_deploy_kit && \
python3 deploy.py
```

**Précision :** les fichiers du kit sont copiés directement dans le dossier courant, sans créer de sous-dossier. Aucun fichier ne doit déjà porter le même nom : le dossier doit donc être vide.

## Desinstallation

**Windows (CMD) :**

```cmd
rmdir /S /Q web_deploy 2>nul & del /Q deploy.py web_deploy_config.json 2>nul & rmdir /S /Q .venv 2>nul
```

**Linux (Terminal) :**

```bash
rm -rf web_deploy deploy.py web_deploy_config.json .venv
```

**Attention :** ces commandes suppriment aussi `.venv`, qui peut contenir des
dépendances propres au projet. Vérifiez son contenu et sauvegardez-le si nécessaire
avant de lancer la commande. Les commandes ne suppriment pas les journaux conservés
dans le dossier utilisateur.

## Exemple

Si votre projet contient :

```text
mon_projet/
├── app/
│   └── server.py
├── web_deploy/
└── deploy.py
```

sélectionnez :

```text
app/server.py
```

Le serveur doit écouter sur l'adresse et le port configurés.

Web Deploy Kit lance Caddy v2 comme reverse proxy pour HTTP et HTTPS :

```text
0.0.0.0:8080 -> application locale 127.0.0.1:8000
```

Installez Caddy séparément avant le déploiement ; le kit vérifie sa version et valide
sa configuration avant de le lancer. Caddy proxy directement vers l'application et
gère les upgrades WebSocket, les réponses en streaming et les requêtes longues. Le
kit ne télécharge ni ne met à jour le binaire Caddy. L'application peut rester liée à
`127.0.0.1`.


## Fonctionnalités actuellement disponibles

Web Deploy Kit couvre aujourd'hui la phase de stabilisation et la V4 côté UX/réseau :

- proxy public local avec Caddy v2 pour HTTP et HTTPS ;
- validation stricte du binaire Caddy, du Caddyfile et des ports avant lancement ;
- authentification Basic optionnelle, liste blanche IP/CIDR, rate limiting et quota quotidien d'upload ;
- coupure puis rétablissement explicites de l'accès public sans arrêter le serveur local ;
- détection de framework Python (Flask, FastAPI, Django, commandes courantes) ;
- supervision du serveur et du proxy avec health checks configurables ;
- diagnostic réseau local : IP publique, CGNAT, double NAT, DNS, pare-feu et redirection NAT ;
- tunnel Cloudflare Quick Tunnel optionnel pour les cas où le routeur ou le réseau ne permet pas de publier directement ;
- tableau de bord d'état avec statut du serveur, du proxy, du tunnel et de l'exposition publique.

Les éléments non encore livrés ou qui restent à formaliser sont notamment la gestion multi-applications et le packaging complet d'installation/désinstallation automatisés.

## Environnement virtuel et dépendances

Lors du déploiement, l'option **Créer/utiliser un venv et installer automatiquement les dépendances** est activée par défaut.

Le kit :

1. crée `.venv/` à la racine du projet s'il n'existe pas ;
2. met à jour `pip` dans ce venv ;
3. installe les dépendances depuis `requirements.txt` s'il existe ;
4. sinon, si `pyproject.toml` ou `setup.py` est présent, installe le projet avec `pip install .` ;
5. lance ensuite le serveur avec le Python du venv, et non avec le Python système.

Pour désactiver ce comportement, décochez l'option dans l'interface.

## Important

Le kit ne configure pas automatiquement tous les routeurs/box Internet. Pour exposer le site sur Internet, configurez sur votre routeur une redirection NAT/port forwarding vers la machine qui exécute le kit.

Exemple :

```text
Port WAN 8080 -> IP locale du PC:8080
```

Une IP publique dynamique peut changer. Pour un vrai service public, un nom de domaine, HTTPS et une solution adaptée de DNS dynamique sont recommandés.

Le kit distingue désormais clairement quatre modes d'exposition :

1. **Proxy local Caddy** : le service est publié via la machine locale, avec ou sans HTTPS.
2. **Tunnel Cloudflare Quick Tunnel** : le trafic public est relayé via le service Cloudflare sans ouvrir de port sur le routeur.
3. **Accès direct sans Caddy** : le serveur est directement lié à toutes les interfaces ; configurez le routeur pour rediriger le port public vers le port serveur.
4. **Aucun accès public** : le serveur reste local et l'application n'est pas exposée.

Le tunnel ne garantit pas un accès Internet "illimité" ni un service public durable ; il fournit une URL temporaire et dépend d'un réseau sortant autorisé vers Cloudflare. Le kit l'affiche comme tel et n'affirme jamais une accessibilité externe lorsqu'il n'a pas de preuve depuis un réseau externe.

## Tunnel Cloudflare Quick Tunnel (optionnel)

Quand le réseau est derrière CGNAT, double NAT ou qu'un routeur bloque les ports publics, le projet peut utiliser un tunnel Cloudflare en sortie.

Le mode tunnel :

- exige le binaire `cloudflared` installé ou configuré via `WEB_DEPLOY_CLOUDFLARED` ;
- démarre un Quick Tunnel vers `http://127.0.0.1:<port_local>` ;
- garde le proxy local Caddy en écoute loopback uniquement pour ne pas exposer le service sans le relais ;
- publie une URL du type `https://<nom>.trycloudflare.com` ;
- s'arrête avant le proxy local et ne conserve pas l'URL après fermeture explicite.

Ce mode est utile pour tester un service public sans configuration NAT, mais il ne remplace pas un déploiement métier avec DNS dédié, certificats permanents et contrôle de sécurité complet.

## HTTPS automatique

Le proxy public requiert Caddy v2 installé sur le PC. Le mode **HTTPS automatique**
nécessite aussi un domaine
public dont l'enregistrement DNS pointe vers l'adresse publique du réseau, et les
ports TCP 80 et 443 accessibles depuis Internet. En mode HTTPS, le port public est
443 ; configurez le routeur pour rediriger WAN 80 vers PC 80 et WAN 443 vers PC 443.
Caddy obtient et renouvelle le certificat automatiquement. Le kit ne télécharge pas
le binaire Caddy ; installation officielle : https://caddyserver.com/docs/install.

L'obtention du certificat échouera notamment si le domaine ne résout pas vers ce
réseau, si le fournisseur utilise un CGNAT, ou si le pare-feu/routeur bloque le port
80 ou 443. Sur Linux, Caddy doit aussi avoir le droit d'écouter sur ces ports.

## Sécurité

L'ouverture d'un port peut rendre l'application et ses fonctions accessibles à
n'importe quel visiteur sur Internet. N'exposez pas une application contenant des
données sensibles ou conçue uniquement pour un usage local. Une confirmation est
demandée avant un déploiement avec le proxy actif et avant l'activation du proxy après
un déploiement local.

Dans **Accès réseau**, activez **Filtrer par IP/CIDR** pour appliquer une liste
d'adresses/plages séparées par des virgules. Une liste vide est refusée au démarrage.
La décision utilise l'adresse du pair transmise par Caddy, pas un en-tête client
direct. Les adresses refusées reçoivent `403`.

**Limiter requêtes/minute/client** est activé par défaut à 120 requêtes/minute ;
décochez-le pour le désactiver. Les requêtes au-delà de la limite reçoivent `429` et
`Retry-After`.

**Quota upload/jour (MiB)** est désactivé par défaut. Quand il est activé, le kit
additionne les octets des corps de requête annoncés par `Content-Length` et réserve
ce volume avant transfert. Le compteur est stocké dans
`~/.web_deploy_kit/security_usage.sqlite3` et se réinitialise à minuit UTC. Il ne
compte ni les réponses téléchargées ni les en-têtes ; une requête interrompue après
réservation reste comptée. Les uploads sans longueur déclarée (par exemple chunked)
reçoivent `411` quand ce quota est actif.

Ces contrôles s'appliquent uniquement lorsque **Proxy public (Caddy)** est actif.
Ils ne remplacent pas un pare-feu et ne protègent pas les fonctions internes de
l'application.

Sans le mode HTTPS Caddy, le trafic n'est pas chiffré : n'envoyez pas de données
sensibles sur le proxy HTTP. Si Basic Auth est activée, le kit demande l'identifiant
et le mot de passe à chaque déploiement ; ils ne sont gardés qu'en mémoire et ne sont
pas écrits dans `web_deploy_config.json`. Le proxy retire l'en-tête Basic avant de
transmettre la requête à l'application.

Le bouton d'accès public permet de couper Caddy sans arrêter le serveur, puis de le
rétablir avec la même politique de sécurité. Si Caddy était désactivé au déploiement,
le bouton affiche **ACTIVER LE PROXY PUBLIC** ; après activation, il devient
**COUPER L'ACCÈS PUBLIC** puis **RÉTABLIR L'ACCÈS PUBLIC** selon son état.

En mode **Accès direct sans Caddy**, le bouton d'accès public indique **ACCÈS DIRECT
ACTIF**. Le service n'est pas protégé par les contrôles Caddy du kit et le trafic est
en HTTP. La règle NAT doit rediriger le port WAN choisi vers le port serveur local, par
exemple `TCP 8080 -> IP_LOCALE_DU_PC:5555`.

## Limites actuelles

- Le serveur Python est lancé comme un processus enfant.
- Caddy v2 est installé et mis à jour séparément ; le kit ne gère pas le téléchargement du binaire.
- Le mode HTTPS automatique nécessite un domaine et l'accessibilité des ports TCP 80/443.
- Le tunnel Cloudflare est optionnel et temporaire ; il ne remplace pas un domaine public stable ni une politique de sécurité permanente.
- Caddy gère WebSocket, streaming et connexions longues ; ces chemins n'ont pas pu être testés avec le vrai binaire ici.
- L'authentification Basic est disponible uniquement avec HTTPS ou le tunnel HTTPS Cloudflare.
- L'allowlist, le rate limit et le quota journalier protègent la passerelle, pas les fonctions internes de l'application.
- La configuration automatique du routeur n'est pas universelle et dépend du modèle.
- Le port choisi doit être disponible et autorisé par le pare-feu.
- Le kit ne vérifie pas lui-même depuis Internet que le pare-feu ou la règle NAT autorise l'accès.
- La gestion multi-applications n'est pas encore livrée dans le code actif ; chaque déploiement est encore un profil unique, même si l'interface et les diagnostics sont déjà préparés pour une extension.


## Tutoriel intégré

Après le choix de la version, l'interface affiche son guide avant la configuration. Les
guides expliquent la préparation de la redirection de ports sur le routeur ; le guide de
la version avancée couvre aussi les vérifications réseau avant le lancement.

Le guide indique :

1. où chercher la fonction NAT / Port Forwarding du routeur ;
2. l'adresse IP locale détectée pour la machine ;
3. le protocole TCP à sélectionner ;
4. le port interne du serveur ;
5. le port externe à ouvrir ;
6. pourquoi il est recommandé de réserver l'adresse IP locale dans le DHCP.

Exemple de règle :

```text
IP interne    : 192.168.1.42
Protocole     : TCP
Port externe : 8080
Port interne : 8000
```

Une fois le guide lu, le bouton `J'AI COMPRIS — CONTINUER` ouvre l'interface principale.


## Adresse publique

L'interface affiche en haut l'adresse publique détectée et un lien cliquable de la forme :

```text
http://IP_PUBLIQUE:PORT_PUBLIC
```

Le port du lien est synchronisé en temps réel avec le champ **Port d'accès**. L'IP publique est rafraîchie périodiquement. Pour que le lien fonctionne depuis Internet, le routeur doit rediriger le port public vers le PC, et le pare-feu Windows/Linux doit autoriser ce port. Certains fournisseurs utilisent un CGNAT : dans ce cas, une simple redirection de port ne suffit pas.

## Diagnostics automatiques

Le journal traduit maintenant plusieurs erreurs courantes en messages lisibles avec une solution courte :

- **PORT DÉJÀ UTILISÉ** — fermer le programme qui utilise le port ou choisir un autre port.
- **PERMISSION REFUSÉE** — utiliser un port supérieur à 1024 et vérifier les droits.
- **SERVEUR INJOIGNABLE** — vérifier que l'application écoute sur le port serveur configuré.
- **FICHIER INTROUVABLE** — vérifier le chemin du projet ou du fichier concerné.
- **DÉPENDANCE PYTHON MANQUANTE** — installer la dépendance dans le venv ou l'ajouter à `requirements.txt`.
- **DÉPENDANCE PYTHON INCOMPATIBLE** — vérifier la version de Python et celle du paquet.
- **DÉLAI D'ATTENTE DÉPASSÉ** — vérifier le démarrage de l'application ou augmenter le délai.
- **ADRESSE RÉSEAU INVALIDE** — vérifier l'adresse d'écoute utilisée par le serveur ou le proxy.
- **CONFIGURATION INVALIDE** — vérifier ou recréer `web_deploy_config.json`.

## Vérification non destructive des ports

Avant le lancement, Web Deployer vérifie que les ports sélectionnés sont disponibles.
Si un port est déjà utilisé, le lancement est refusé et le journal affiche le PID ainsi
que le nom du processus lorsque le système peut le fournir. Le kit n'arrête jamais un
processus externe pour libérer un port : choisissez un autre port ou arrêtez vous-même
le programme concerné.

Lors d'un arrêt, le kit ne gère que le serveur et le proxy qu'il a lui-même lancés.
Si l'arrêt normal du serveur échoue, l'interface demande confirmation avant de
forcer l'arrêt. Sans confirmation, le processus reste géré et son état est conservé.

## Supervision et journaux

Après le déploiement, le kit vérifie périodiquement la réponse HTTP du serveur et du
proxy. Après deux vérifications échouées, l'accès public est arrêté. Le redémarrage
automatique est désactivé par défaut ; s'il est activé dans l'interface, le nombre
de tentatives et l'intervalle de vérification sont réglables dans l'interface.

Le bouton **ARRÊTER** ferme le proxy puis le serveur. La fermeture de l'interface
déclenche également l'arrêt propre des services.

Les journaux sont conservés dans `~/.web_deploy_kit/logs/web-deployer.log` (dans le
dossier personnel de l'utilisateur), avec rotation à 2 MiB et conservation de cinq
fichiers. La sortie du serveur est incluse. Sous Linux et macOS, le fichier courant
est créé avec des permissions privées pour l'utilisateur. Les journaux peuvent
contenir des informations écrites par l'application ; vérifiez-les avant de les
partager.

## Détection du serveur et santé

Le bouton **Détecter** analyse statiquement les fichiers Python et les dépendances
pour suggérer Flask, FastAPI ou Django, un fichier d'entrée, un port et une commande.
Le code du projet n'est ni importé ni exécuté pendant cette détection. Vérifiez les
suggestions avant de lancer : elles restent modifiables, et la sélection manuelle
reste disponible si le framework est inconnu.

Dans **Health check**, choisissez le chemin HTTP, le code attendu et le timeout. Les
valeurs initiales sont `GET /`, `200` et `3 s`; la vérification périodique utilise
l'intervalle défini dans les options. Le serveur local est vérifié séparément du
proxy Caddy. Caddy effectue aussi des vérifications actives de l'upstream. Les
réponses d'authentification `401/403` du proxy ne sont pas interprétées comme une
panne de l'application.

## Tests

Exécutez les tests locaux avec la bibliothèque standard Python :

```bash
python3 -m unittest discover -s tests -v
```

## Base locale des ports

Web Deployer inclut une petite base SQLite locale : `web_deploy/data/ports.db`.

Elle contient notamment :

- des ports connus comme sensibles ou refusés par certains navigateurs (`browser_unsafe`) ;
- des ports souvent réservés à des services réseau et susceptibles d'être filtrés par certaines box/routeurs (`router_reserved`) ;
- quelques ports courants adaptés à un service Web (`recommended`).

La base sert à prévenir les erreurs avant le déploiement. Elle ne prétend pas connaître les règles particulières de chaque routeur ou fournisseur d'accès : le filtrage des ports publics dépend de l'équipement et du réseau.

Le port public est contrôlé avant le lancement. Un port classé `browser_unsafe` bloque le déploiement avec une proposition de ports alternatifs. L'interface permet aussi de vérifier manuellement le port public.
