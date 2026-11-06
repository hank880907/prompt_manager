import sqlite3

from prompt_manager.config import DATA_DIR

conn = sqlite3.connect(DATA_DIR / "prompts.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA synchronous = NORMAL")
conn.executescript("""
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT,  -- set only on private projects
    default_aspect_ratio TEXT NOT NULL DEFAULT '16:9'
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
    aspect_ratio TEXT NOT NULL DEFAULT '16:9',
    position INTEGER NOT NULL DEFAULT 0,
    selected_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    filename TEXT NOT NULL
);
""")
project_columns = [c["name"] for c in conn.execute("PRAGMA table_info(projects)")]
if "owner" not in project_columns:
    with conn:
        conn.execute("ALTER TABLE projects ADD COLUMN owner TEXT")
if "default_aspect_ratio" not in project_columns:
    with conn:
        conn.execute("ALTER TABLE projects ADD COLUMN default_aspect_ratio TEXT NOT NULL DEFAULT '16:9'")
scene_columns = [c["name"] for c in conn.execute("PRAGMA table_info(scenes)")]
if "position" not in scene_columns:
    with conn:
        conn.execute("ALTER TABLE scenes ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE scenes SET position = id")
if "aspect_ratio" not in scene_columns:
    with conn:
        conn.execute("ALTER TABLE scenes ADD COLUMN aspect_ratio TEXT NOT NULL DEFAULT '16:9'")
if "selected_image_id" not in scene_columns:
    with conn:
        conn.execute("ALTER TABLE scenes ADD COLUMN selected_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL")


# Pass the owner twice; None (trusted API caller) sees everything.
VISIBLE = "(p.owner IS NULL OR ? IS NULL OR p.owner = ?)"


def query(sql: str, *args) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def get(sql: str, *args) -> sqlite3.Row | None:
    return conn.execute(sql, args).fetchone()


def execute(sql: str, *args) -> int:
    with conn:
        return conn.execute(sql, args).lastrowid


def visible_scene(scene_id: int, owner: str | None, columns: str = "s.id") -> sqlite3.Row | None:
    return get(f"SELECT {columns} FROM scenes s JOIN episodes e ON e.id = s.episode_id "
               f"JOIN projects p ON p.id = e.project_id WHERE s.id = ? AND {VISIBLE}", scene_id, owner, owner)


def execute_many(sql: str, rows: list[tuple]) -> None:
    with conn:
        conn.executemany(sql, rows)
