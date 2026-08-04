# Maintenance Silo

Application Django de gestion des maintenances (pannes et préventives) pour les silos agricoles.

## Fonctionnalités

- **Trois rôles** : Administrateur, Agent de maintenance, Agent de silo
- **Pannes** : déclaration, affectation, workflow d'états, médias joints, factures
- **Maintenances préventives** : création/envoi par l'agent maintenance, réception/démarrage/clôture par l'agent silo avec compte rendu obligatoire, validation/rejet par l'agent maintenance
- **Permissions par site** : chaque utilisateur ne voit que les objets de ses sites autorisés
- **Notifications persistantes** + diffusion WebSocket temps réel (Django Channels + Redis)
- **Commande `mark_overdue`** : passe les tâches échues en retard (idempotente, prévue pour cron/Celery)
- **Uploads** : validation extension, MIME et taille configurable
- **Dashboards** adaptés par rôle (admin, maintenance, silo)

## Démarrage rapide (Docker)

```bash
cp .env.example .env
# Éditer .env : changer SECRET_KEY et les mots de passe PostgreSQL
docker compose up --build
```

Dans un autre terminal :

```bash
docker compose exec web python manage.py createsuperuser
# Données de démonstration :
docker compose exec web python manage.py seed_demo
```

| URL | Description |
|-----|-------------|
| `http://localhost:8000/` | Application |
| `http://localhost:8000/admin/` | Administration Django |
| `http://localhost:8000/auth/login/` | Connexion |

## Démarrage sans Docker (SQLite)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
export USE_SQLITE=true

python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

## Tests

```bash
USE_SQLITE=true python manage.py test maintenance --verbosity=2
```

## Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `SECRET_KEY` | Clé secrète Django (**changer en production**) | `dev-only-...` |
| `DEBUG` | Mode debug | `True` |
| `ALLOWED_HOSTS` | Hôtes autorisés | `localhost,127.0.0.1` |
| `POSTGRES_*` | Connexion PostgreSQL | — |
| `REDIS_URL` | URL Redis pour WebSockets | `redis://localhost:6379/1` |
| `USE_SQLITE` | SQLite (dev/tests) | `False` |
| `MAX_UPLOAD_SIZE` | Taille max upload (octets) | `10485760` (10 Mo) |
| `ALLOWED_UPLOAD_EXTENSIONS` | Extensions autorisées | `jpg,jpeg,png,pdf,...` |

## Commandes de gestion

```bash
# Données de démonstration
python manage.py seed_demo [--reset]

# Marquer les tâches préventives en retard
python manage.py mark_overdue [--dry-run]
```

Exemple cron (toutes les heures) :
```
0 * * * * /app/.venv/bin/python /app/manage.py mark_overdue
```

## Rôles et permissions

| Action | Admin | Maintenance | Silo |
|--------|-------|-------------|------|
| Voir toutes les pannes du site | ✓ | ✓ | Ses pannes uniquement |
| Déclarer une panne | ✓ | ✓ | ✓ |
| Affecter une panne | ✓ | ✓ | ✗ |
| Changer le statut d'une panne | ✓ | ✓ | ✗ |
| Créer une tâche préventive | ✓ | ✓ | ✗ |
| Recevoir / démarrer / terminer une tâche | ✗ | ✗ | ✓ |
| Valider / rejeter une tâche | ✓ | ✓ | ✗ |
| Ajouter une facture | ✓ | ✓ | ✗ |

## Sécurité

- `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS` **obligatoires** en production
- Fichiers uploadés validés par extension, MIME et taille
- HTTPS + HSTS activés automatiquement quand `DEBUG=False`
- Ne jamais committer `.env` avec de vrais secrets
- Mots de passe `seed_demo` uniquement pour le développement

## CI

GitHub Actions `.github/workflows/ci.yml` : `pip install`, `manage.py check`, `makemigrations --check`, tests SQLite.

## Limites connues

- WebSocket (Channels + Redis) non testé en CI
- Templates Bootstrap via CDN (télécharger localement pour les environnements sans Internet)
- Pas de pagination dans les listes
- Reset mot de passe par email non configuré (ajouter `EMAIL_*` dans `.env`)
