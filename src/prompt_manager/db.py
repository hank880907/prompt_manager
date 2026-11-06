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
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    positive TEXT NOT NULL DEFAULT '',
    negative TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS character_images (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    view TEXT NOT NULL,
    filename TEXT NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS character_references (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    filename TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    prompt_id TEXT PRIMARY KEY,
    scene_id INTEGER REFERENCES scenes(id) ON DELETE CASCADE,
    character_id INTEGER REFERENCES characters(id) ON DELETE CASCADE,
    view TEXT
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


# Keys match VIEWS in the ComfyUI node.
VIEWS = {
    "front": "正面全身",
    "three_quarter": "四分之三侧面全身",
    "side": "侧面全身",
    "back": "背面全身",
    "face": "正脸特写",
    "face_three_quarter": "四分之三侧脸特写",
    "seated": "坐姿中景",
}

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


def visible_character(character_id: int, owner: str | None, columns: str = "c.id") -> sqlite3.Row | None:
    return get(f"SELECT {columns} FROM characters c JOIN projects p ON p.id = c.project_id "
               f"WHERE c.id = ? AND {VISIBLE}", character_id, owner, owner)


def scene_labels(owner: str | None) -> list[dict]:
    rows = query(f"""
        SELECT s.id, p.name AS project, e.name AS episode, s.name,
               ROW_NUMBER() OVER (PARTITION BY s.episode_id ORDER BY s.position) AS n
        FROM scenes s JOIN episodes e ON e.id = s.episode_id JOIN projects p ON p.id = e.project_id
        WHERE {VISIBLE} ORDER BY p.id, e.id, s.position
    """, owner, owner)
    return [{"id": r["id"], "label": f"{r['project']} / {r['episode']} / {r['n']}. {r['name']} #{r['id']}"} for r in rows]


def character_label(row) -> str:
    return f"{row['project']} / {row['name']} #{row['id']}"


def selected_front(character_id: int) -> sqlite3.Row | None:
    return get("SELECT * FROM character_images WHERE character_id = ? AND view = 'front' AND selected",
               character_id)


def execute_many(sql: str, rows: list[tuple]) -> None:
    with conn:
        conn.executemany(sql, rows)
