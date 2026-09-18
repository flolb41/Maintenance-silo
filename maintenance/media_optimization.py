import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile


logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".webm"}


def optimiser_media_televerse(fichier, nom_original=None):
    if not getattr(settings, "MEDIA_OPTIMIZATION_ENABLED", True):
        return None

    nom = nom_original or getattr(fichier, "name", "media")
    extension = Path(nom).suffix.lower()

    try:
        if extension in IMAGE_EXTENSIONS:
            return _optimiser_image(fichier, nom)
        if extension in VIDEO_EXTENSIONS:
            return _optimiser_video(fichier, nom)
    except Exception:
        logger.exception("Optimisation impossible pour le média %s", nom)
    finally:
        _rembobiner(fichier)
    return None


def _optimiser_image(fichier, nom_original):
    from PIL import Image, ImageOps, ImageSequence

    donnees_originales = _lire_fichier(fichier)
    image = Image.open(BytesIO(donnees_originales))
    sortie = BytesIO()
    qualite = max(
        1, min(100, int(getattr(settings, "MEDIA_IMAGE_WEBP_QUALITY", 90)))
    )

    if getattr(image, "is_animated", False):
        images = [frame.convert("RGBA")
                  for frame in ImageSequence.Iterator(image)]
        durees = [
            frame.info.get("duration", image.info.get("duration", 100))
            for frame in ImageSequence.Iterator(image)
        ]
        images[0].save(
            sortie,
            format="WEBP",
            save_all=True,
            append_images=images[1:],
            duration=durees,
            loop=image.info.get("loop", 0),
            quality=qualite,
            method=6,
        )
    else:
        image = ImageOps.exif_transpose(image)
        avec_transparence = image.mode in {"LA", "RGBA"} or (
            image.mode == "P" and "transparency" in image.info
        )
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if avec_transparence else "RGB")
        image.save(
            sortie,
            format="WEBP",
            lossless=avec_transparence or Path(
                nom_original).suffix.lower() == ".png",
            quality=qualite,
            method=6,
            exact=avec_transparence,
        )

    donnees_optimisees = sortie.getvalue()
    if len(donnees_optimisees) >= len(donnees_originales):
        return None
    return ContentFile(
        donnees_optimisees,
        name=f"{Path(nom_original).stem}.webp",
    )


def _optimiser_video(fichier, nom_original):
    ffmpeg = getattr(settings, "FFMPEG_BINARY", "ffmpeg")
    if not shutil.which(ffmpeg) and not Path(ffmpeg).is_file():
        logger.warning(
            "FFmpeg indisponible, vidéo conservée sans modification")
        return None

    entree = None
    sortie = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=Path(nom_original).suffix, delete=False
        ) as fichier_entree:
            entree = fichier_entree.name
            fichier_entree.write(_lire_fichier(fichier))
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as fichier_sortie:
            sortie = fichier_sortie.name

        commande = [
            ffmpeg,
            "-y",
            "-i",
            entree,
            "-map_metadata",
            "-1",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            str(getattr(settings, "MEDIA_VIDEO_CRF", 28)),
            "-b:v",
            "0",
            "-deadline",
            "good",
            "-cpu-used",
            "2",
            "-row-mt",
            "1",
            "-c:a",
            "libopus",
            "-b:a",
            "160k",
            sortie,
        ]
        subprocess.run(
            commande,
            check=True,
            capture_output=True,
            timeout=getattr(settings, "MEDIA_VIDEO_TIMEOUT", 300),
        )
        with open(sortie, "rb") as resultat:
            donnees_optimisees = resultat.read()
        taille_originale = os.path.getsize(entree)
        if not donnees_optimisees or len(donnees_optimisees) >= taille_originale:
            return None
        return ContentFile(
            donnees_optimisees,
            name=f"{Path(nom_original).stem}.webm",
        )
    finally:
        for chemin in (entree, sortie):
            if chemin:
                try:
                    os.unlink(chemin)
                except FileNotFoundError:
                    pass


def _lire_fichier(fichier):
    _rembobiner(fichier)
    donnees = fichier.read()
    _rembobiner(fichier)
    return donnees


def _rembobiner(fichier):
    try:
        fichier.seek(0)
    except (AttributeError, OSError):
        pass
