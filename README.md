# Maintenance Silo

Application Django de gestion des maintenances (pannes et préventives) pour les silos agricoles.

## Fonctionnalités

- **Trois rôles** : Administrateur, Agent de maintenance, Agent de silo
- **Pannes** : déclaration, affectation, workflow d'états, médias joints, factures
- **Maintenances préventives** : tâches ponctuelles ou périodiques (mensuelles, trimestrielles, annuelles), génération automatique, réception/démarrage/clôture avec compte rendu obligatoire
- **Permissions métier** : les agents silo sont limités à leur site et à leurs tâches ; les administrateurs et agents maintenance interviennent sur l’ensemble du parc selon leur rôle
- **Notifications persistantes** + diffusion WebSocket temps réel (Django Channels + Redis)
- **Commande `mark_overdue`** : passe les tâches échues en retard (idempotente, prévue pour cron/Celery)
- **Uploads** : validation extension, MIME et taille configurable
- **Dashboards** adaptés par rôle (admin, maintenance, silo)
- **Calendrier des échéances** : préventives, entretiens véhicules, VGP et passages aux mines
- **Pièces détachées** : stock par site, seuils d'alerte et mouvements d'entrée/sortie
- **QR codes équipements** pour l'identification terrain
- **Indicateurs** : tendance des pannes, coûts facturés et durée moyenne d'intervention
- **PWA terrain** avec cache hors-ligne et mise en file des déclarations sans média

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
| `CSRF_TRUSTED_ORIGINS` | Origines HTTPS autorisées, séparées par des virgules | vide |
| `POSTGRES_*` | Connexion PostgreSQL | — |
| `REDIS_URL` | URL Redis pour WebSockets | `redis://localhost:6379/1` |
| `USE_SQLITE` | SQLite (dev/tests) | `False` |
| `MAX_UPLOAD_SIZE` | Taille max upload (octets) | `10485760` (10 Mo) |
| `MAX_FILES_PER_UPLOAD` | Nombre maximal de fichiers par import multiple | `20` |
| `MEDIA_OPTIMIZATION_ENABLED` | Optimise automatiquement les photos et vidéos | `True` |
| `MEDIA_IMAGE_WEBP_QUALITY` | Qualité visuelle des images WebP (1 à 100) | `90` |
| `MEDIA_VIDEO_CRF` | Qualité vidéo VP9, plus bas = meilleure qualité | `28` |
| `MEDIA_VIDEO_TIMEOUT` | Durée maximale d'un encodage vidéo en secondes | `300` |
| `FFMPEG_BINARY` | Chemin de l'exécutable FFmpeg | `ffmpeg` |
| `ALLOWED_UPLOAD_EXTENSIONS` | Extensions autorisées | `jpg,jpeg,png,pdf,...` |
| `EMAIL_BACKEND` | Backend d’envoi des e-mails | Console en développement |
| `EMAIL_HOST` / `EMAIL_PORT` | Serveur SMTP | `localhost` / `587` |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | Identifiants SMTP | — |
| `EMAIL_USE_TLS` | Active TLS pour SMTP | `True` |
| `EMAIL_USE_SSL` | Active SSL implicite (exclusif avec TLS) | `False` |
| `EMAIL_TIMEOUT` | Délai maximal de connexion SMTP en secondes | `15` |
| `DEFAULT_FROM_EMAIL` | Adresse expéditrice | `ne-pas-repondre@...` |

## Commandes de gestion

```bash
# Données de démonstration
python manage.py seed_demo [--reset]

# Marquer les tâches préventives en retard
python manage.py mark_overdue [--dry-run]

# Générer les occurrences périodiques dans les 31 prochains jours
python manage.py generate_recurring_preventives [--days-ahead 31] [--dry-run]
```

Exemple cron (toutes les heures) :
```
0 * * * * /app/.venv/bin/python /app/manage.py mark_overdue
15 0 * * * /app/.venv/bin/python /app/manage.py generate_recurring_preventives --days-ahead 31
```

La commande de génération est idempotente : elle peut être relancée sans créer de doublon. Sur Windows, la même commande peut être programmée quotidiennement avec le Planificateur de tâches.

## Optimisation des médias

Les photos de sites, de véhicules, de pannes et de tâches préventives sont converties en **WebP** sans redimensionnement. Les images avec transparence et les PNG utilisent le mode sans perte. Les vidéos sont converties en **WebM** avec les codecs VP9 et Opus. Un fichier optimisé ne remplace l'original que s'il occupe réellement moins d'espace.

FFmpeg est installé automatiquement dans l'image Docker. Pour une installation sans Docker, installez FFmpeg et rendez la commande `ffmpeg` accessible dans le `PATH`, ou indiquez son chemin dans `FFMPEG_BINARY`. Si Pillow, FFmpeg ou un codec est indisponible, l'upload reste fonctionnel et le fichier original est conservé.

## Détection des factures

Les PDF texte, documents Word et fichiers Excel sont lus directement. Pour détecter le contenu des photos et des PDF scannés, installez également **Tesseract OCR** et **Poppler** sur le serveur, puis rendez les commandes `tesseract` et `pdftoppm` accessibles dans le `PATH`. Sans ces exécutables, la facture reste importée et signalée « À vérifier », mais le texte d'une image ne peut pas être reconnu automatiquement.

## Rôles et permissions

| Action | Admin | Maintenance | Silo |
|--------|-------|-------------|------|
| Voir toutes les pannes du site | ✓ | ✓ | Ses pannes uniquement |
| Déclarer une panne | ✓ | ✗ | ✓ |
| Affecter une panne | ✓ | ✗ | ✗ |
| Changer le statut d'une panne | ✓ | Si elle lui est affectée | ✗ |
| Créer une tâche préventive | ✓ | ✗ | ✗ |
| Recevoir / démarrer / terminer une tâche | ✗ | ✗ | ✓ |
| Valider / rejeter une tâche | ✓ | Si liée à sa panne active | ✗ |
| Ajouter une facture | ✓ | ✗ | ✗ |

## Sécurité

- `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS` **obligatoires** en production
- Fichiers uploadés validés par extension, MIME et taille
- Fichiers statiques collectés et servis par WhiteNoise sous Uvicorn
- HTTPS + HSTS activés automatiquement quand `DEBUG=False`
- En production, placer Uvicorn derrière un proxy HTTPS transmettant `X-Forwarded-Proto` et renseigner `CSRF_TRUSTED_ORIGINS`
- Ne jamais committer `.env` avec de vrais secrets
- Mots de passe `seed_demo` uniquement pour le développement

## CI

GitHub Actions `.github/workflows/ci.yml` : `pip install`, `manage.py check`, `makemigrations --check`, tests SQLite.

## Limites connues

- WebSocket (Channels + Redis) non testé en CI
- Templates Bootstrap via CDN (télécharger localement pour les environnements sans Internet)
- Pas de pagination dans les listes
- L’envoi réel des e-mails nécessite de copier `.env.example` vers `.env`, puis de renseigner les variables SMTP `EMAIL_*`. Vérifiez la connexion avec `python manage.py sendtestemail destinataire@example.com`. Microsoft 365 peut exiger l’activation de SMTP AUTH pour la boîte utilisée ; utilisez un mot de passe d’application si l’authentification multifacteur l’impose.
