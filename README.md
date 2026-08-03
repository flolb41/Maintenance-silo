# Maintenance Silo

Application Django de gestion de maintenance de silos à grains.  
Socle minimal : Django 5, Django Channels, Redis, PostgreSQL, Docker.

## Architecture

```
maintenance-silo/
├── config/          # Paramètres, ASGI, URLs, routage WebSocket
├── maintenance/     # Application principale (modèles, admin, consumers)
├── templates/       # Templates Django (base.html)
├── static/js/       # JavaScript vanilla (WebSocket)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Fichiers ajoutés

| Fichier | Rôle |
|---|---|
| `config/settings.py` | Paramètres Django (PostgreSQL, Redis, Channels) |
| `config/asgi.py` | Point d'entrée ASGI / Daphne |
| `config/routing.py` | Routage WebSocket global |
| `config/urls.py` | URLs HTTP (admin + médias en dev) |
| `maintenance/models.py` | Modèles : Profile, Site, Equipement, Panne, PanneMedia, MaintenancePreventive, Facture, Notification |
| `maintenance/admin.py` | Administration Django des modèles |
| `maintenance/consumers.py` | Consumer WebSocket authentifié (`/ws/realtime/`) |
| `maintenance/realtime.py` | Utilitaire `diffuser_evenement()` |
| `static/js/realtime.js` | WebSocket JavaScript vanilla |
| `templates/base.html` | Template de base |
| `Dockerfile` | Image Python 3.12 + Daphne |
| `docker-compose.yml` | Services web, PostgreSQL 16, Redis 7 |
| `.env.example` | Variables d'environnement |
| `.gitignore` | Fichiers ignorés par Git |

## Prérequis

- Python 3.12+
- Docker et Docker Compose

## Installation locale

```bash
# 1. Copier la configuration
cp .env.example .env

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Démarrer PostgreSQL et Redis (ou adapter .env pour des services locaux)

# 4. Créer les migrations et migrer
python manage.py makemigrations maintenance
python manage.py migrate

# 5. Créer un superutilisateur
python manage.py createsuperuser

# 6. Lancer le serveur ASGI
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

## Démarrage avec Docker

```bash
# 1. Copier la configuration
cp .env.example .env

# 2. Construire et démarrer les services
docker compose up --build

# Dans un second terminal :
docker compose exec web python manage.py makemigrations maintenance
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## Accès

| Service | URL |
|---|---|
| Application | http://localhost:8000/ |
| Administration | http://localhost:8000/admin/ |
| WebSocket | ws://localhost:8000/ws/realtime/ |

## Modèles

| Modèle | Description |
|---|---|
| `Profile` | Rôle utilisateur : administrateur, agent de maintenance, agent de silo |
| `Site` | Site avec utilisateurs autorisés |
| `Equipement` | Équipement lié à un site |
| `Panne` | Panne avec déclarant, agent assigné, priorité et statut |
| `PanneMedia` | Fichiers joints à une panne (photos, vidéos, documents) |
| `MaintenancePreventive` | Tâche de maintenance avec créateur, destinataire, échéance et retour |
| `Facture` | Facture liée à une panne |
| `Notification` | Notification persistante par utilisateur |

## Temps réel

Le consumer WebSocket `/ws/realtime/` exige une authentification.  
Pour diffuser un événement depuis le code Django :

```python
from maintenance.realtime import diffuser_evenement

diffuser_evenement("panne_creee", {"id": 1, "titre": "Moteur HS"})
```

Le JavaScript vanilla (`static/js/realtime.js`) ouvre la connexion et dispatche les événements reçus via `CustomEvent("maintenance-event")`.

## Limites de ce socle minimal

- Pas de vues ni de formulaires Django (hors administration).
- Pas de permissions par rôle ni par site.
- Pas de déclenchement automatique des notifications.
- Pas de tests automatisés.
- Pas de collecte des fichiers statiques en production (à configurer).

Ces éléments sont prévus pour les prochaines itérations.