import ipaddress
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
IMAGES_DIR = DATA_DIR / "images"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
PREVIEWS_DIR = DATA_DIR / "previews"
for directory in (IMAGES_DIR, THUMBNAILS_DIR, PREVIEWS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NICEGUI_STORAGE_PATH", str(DATA_DIR / ".nicegui"))

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
TRUSTED_NETWORKS = [ipaddress.ip_network(n.strip()) for n in os.environ.get("TRUSTED_IPS", "").split(",") if n.strip()]
