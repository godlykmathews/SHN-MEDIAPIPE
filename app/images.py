import io
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 25_000_000


def save_image(raw: bytes, directory: Path, scan_id: str):
    """Decode, strip metadata, fix phone orientation, and save bounded RGB images."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('Use a JPG, PNG, or WebP photograph.')
                source.load()
                if min(source.size) < 32:
                    raise ValueError('This image is too small. Use a photo at least 32 pixels wide and tall.')
                picture = ImageOps.exif_transpose(source).convert('RGB')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('This image could not be opened, or exceeds the 25 megapixel limit.') from exc
    picture.thumbnail((1800, 1800))
    picture.save(directory / f'{scan_id}.jpg', 'JPEG', quality=92)
    picture.thumbnail((480, 480))
    picture.save(directory / f'{scan_id}.thumb.jpg', 'JPEG', quality=85)
