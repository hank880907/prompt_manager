import sqlite3
from pathlib import Path

IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)

conn = sqlite3.connect("prompts.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.executescript("""
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    image_positive TEXT NOT NULL DEFAULT '',
    image_negative TEXT NOT NULL DEFAULT '',
    video_prompt TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    selected_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    filename TEXT NOT NULL
);
""")
scene_columns = [c["name"] for c in conn.execute("PRAGMA table_info(scenes)")]
if "position" not in scene_columns:
    with conn:
        conn.execute("ALTER TABLE scenes ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE scenes SET position = id")
if "selected_image_id" not in scene_columns:
    with conn:
        conn.execute("ALTER TABLE scenes ADD COLUMN selected_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL")


def query(sql: str, *args) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def get(sql: str, *args) -> sqlite3.Row | None:
    return conn.execute(sql, args).fetchone()


def execute(sql: str, *args) -> int:
    with conn:
        return conn.execute(sql, args).lastrowid
