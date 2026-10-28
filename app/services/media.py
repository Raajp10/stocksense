from pathlib import Path
from uuid import uuid4
from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import current_app
from .common import DomainError

Image.MAX_IMAGE_PIXELS = 16_000_000


def save_image(upload):
    data = upload.read(5*1024*1024+1)
    if len(data) > 5*1024*1024:
        raise DomainError("Photo must be no larger than 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ("JPEG", "PNG", "WEBP"):
                    raise DomainError("Choose a JPEG, PNG or WebP photo.")
                if source.width*source.height > 16_000_000:
                    raise DomainError("Photo exceeds the 16 megapixel limit.")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1200, 1200))
                key = uuid4().hex+".jpg"
                image.save(Path(current_app.config["UPLOAD_DIR"])/key, "JPEG", quality=85)
                return key
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise DomainError("The uploaded file is not a safe, valid image.") from exc


def remove_image(key):
    if key and key.endswith(".jpg") and len(key) == 36:
        (Path(current_app.config["UPLOAD_DIR"])/key).unlink(missing_ok=True)
