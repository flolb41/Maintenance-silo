# Maintenance Silo

Application web Django de gestion de maintenance pour silos à grains.

## Fonctionnalités

- **Gestion des pannes** : signalement, affectation, suivi des statuts (7 états), historique immuable, pièces jointes
- **Maintenances préventives** : planification, suivi des échéances (10 états), retour d'intervention
- **Factures** : création liée à une panne ou préventive, validation HT+TVA=TTC
- **Notifications temps réel** via Django Channels / WebSocket (reconnexion automatique)
- **Rôles** : Administrateur, Équipe maintenance, Agent silo — chaque rôle voit ses propres données
- **Dashboard** différencié par rôle : KPIs admin, pannes affectées maintenance, mes pannes silo
- **Référentiel** : gestion des sites et équipements

## Stack technique

- Django 5/6 + Django Channels + Daphne (ASGI)
- Redis (channel layer WebSocket)
- PostgreSQL (production) / SQLite (dev/CI)
- Bootstrap 5 (CDN) — aucun framework frontend SPA
- Docker + Docker Compose

## Démarrage rapide (Docker)

```bash
cp .env.example .env
docker compose up --build
```

L'application est disponible sur http://localhost:8000.

Charger les données de démo :

```bash
docker compose exec web python manage.py seed_demo
```

Comptes de démo :

| Username | Mot de passe | Rôle |
|---|---|---|
| admin | admin123 | Administrateur |
| technicien | tech123 | Équipe maintenance |
| agent_silo | silo123 | Agent silo |

## Démarrage en développement (SQLite)

```bash
pip install -r requirements.txt
USE_SQLITE=true python manage.py migrate
USE_SQLITE=true python manage.py seed_demo
USE_SQLITE=true python manage.py runserver
```

> **Note :** Les WebSockets (notifications temps réel) nécessitent Redis et Daphne.
> En dev avec `runserver`, le serveur WSGI classique fonctionne mais les WebSockets sont inactifs.

## Commandes de gestion

```bash
# Passer les préventives échues à "en_retard" (à planifier en cron)
python manage.py mark_overdue

# Charger les données de démo
python manage.py seed_demo
```

## Structure du projet

```
config/          # Settings, ASGI, URLs racines
maintenance/
  models.py      # 11 modèles (Site, Profile, Equipement, Panne, ...)
  views.py       # Toutes les vues (CBV + FBV)
  forms.py       # Formulaires avec validation
  mixins.py      # Mixins de permissions par rôle
  consumers.py   # Consumer WebSocket (Channels)
  signals.py     # Signaux post_save → notifications
  context_processors.py  # Compteur de notifications non lues
  management/commands/   # mark_overdue, seed_demo
templates/maintenance/   # Templates Bootstrap 5
```

## Transitions de statuts

### Panne (7 statuts)
```
nouvelle → affectée → en_cours → [en_attente_pieces | résolue]
résolue → fermée
*tout → annulée
```

### Maintenance préventive (10 statuts)
```
planifiée → [en_cours | annulée | en_retard | reportée]
en_cours → [en_attente_pieces | effectuée | partielle]
effectuée → validée → archivée
```
