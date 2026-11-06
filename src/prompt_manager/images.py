import io
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
from nicegui import app
from PIL import Image, ImageOps

from prompt_manager.config import IMAGES_DIR, PREVIEWS_DIR, THUMBNAILS_DIR
from prompt_manager.db import query

app.add_static_files("/images", IMAGES_DIR, max_cache_age=31536000)


def resized(filename: str, directory: Path, size: int) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}\.png", filename) or not (IMAGES_DIR / filename).exists():
        raise HTTPException(404, "image not found")
    target = directory / f"{Path(filename).stem}.webp"
    if not target.exists():
        temp = directory / f"{uuid4().hex}.tmp"
        with Image.open(IMAGES_DIR / filename) as image:
            image.thumbnail((size, size))
            image.convert("RGB").save(temp, "WEBP", quality=80)
        temp.replace(target)
    return FileResponse(target, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


def save_png(data: bytes) -> str:
    filename = f"{uuid4().hex}.png"
    with Image.open(io.BytesIO(data)) as image:
        ImageOps.exif_transpose(image).convert("RGB").save(IMAGES_DIR / filename, "PNG")
    return filename


def image_size(filename: str) -> tuple[int, int]:
    with Image.open(IMAGES_DIR / filename) as image:
        return image.size


@app.get("/thumbnails/{filename}")
def thumbnail(filename: str):
    return resized(filename, THUMBNAILS_DIR, 384)


@app.get("/previews/{filename}")
def preview(filename: str):
    return resized(filename, PREVIEWS_DIR, 1600)


def remove_orphans() -> None:
    """Delete image files whose rows are gone, e.g. after a project, episode or scene was deleted."""
    known = {row["filename"] for row in query(
        "SELECT filename FROM images UNION SELECT filename FROM character_images "
        "UNION SELECT filename FROM character_references")}
    for file in IMAGES_DIR.iterdir():
        if file.name not in known:
            file.unlink()
    for file in [*THUMBNAILS_DIR.iterdir(), *PREVIEWS_DIR.iterdir()]:
        if f"{file.stem}.png" not in known:
            file.unlink()
