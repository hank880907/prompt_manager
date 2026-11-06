from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from nicegui import app, run

from prompt_manager.config import IMAGES_DIR
from prompt_manager.db import VIEWS, VISIBLE, execute, query, selected_front, visible_character, visible_scene


@app.get("/api/scenes")
async def list_scenes(request: Request):
    owner = request.state.owner
    rows = query(f"""
        SELECT s.id, p.name AS project, e.name AS episode, s.name,
               ROW_NUMBER() OVER (PARTITION BY s.episode_id ORDER BY s.position) AS n
        FROM scenes s JOIN episodes e ON e.id = s.episode_id JOIN projects p ON p.id = e.project_id
        WHERE {VISIBLE} ORDER BY p.id, e.id, s.position
    """, owner, owner)
    return [{"id": r["id"], "label": f"{r['project']} / {r['episode']} / {r['n']}. {r['name']} #{r['id']}"}
            for r in rows]


@app.get("/api/scenes/{scene_id}")
async def get_scene(scene_id: int, request: Request):
    scene = visible_scene(scene_id, request.state.owner, "s.image_positive, s.image_negative, s.video_prompt, s.aspect_ratio")
    if not scene:
        raise HTTPException(404, "scene not found")
    return dict(scene)


@app.post("/api/scenes/{scene_id}/images")
async def upload_image(scene_id: int, request: Request):
    if not visible_scene(scene_id, request.state.owner):
        raise HTTPException(404, "scene not found")
    filename = await save_upload(request)
    execute("INSERT INTO images (scene_id, filename) VALUES (?, ?)", scene_id, filename)
    return {"filename": filename}


async def save_upload(request: Request) -> str:
    filename = f"{uuid4().hex}.png"
    await run.io_bound((IMAGES_DIR / filename).write_bytes, await request.body())
    return filename


@app.get("/api/characters")
async def list_characters(request: Request):
    owner = request.state.owner
    rows = query(f"SELECT c.id, p.name AS project, c.name FROM characters c JOIN projects p ON p.id = c.project_id "
                 f"WHERE {VISIBLE} ORDER BY p.id, c.id", owner, owner)
    return [{"id": r["id"], "label": f"{r['project']} / {r['name']} #{r['id']}"} for r in rows]


@app.get("/api/characters/{character_id}")
async def get_character(character_id: int, request: Request):
    character = visible_character(character_id, request.state.owner, "c.positive, c.negative")
    if not character:
        raise HTTPException(404, "character not found")
    front = selected_front(character_id)
    return {**dict(character), "reference": front and front["filename"]}


@app.get("/api/characters/{character_id}/reference")
async def get_reference(character_id: int, request: Request):
    front = visible_character(character_id, request.state.owner) and selected_front(character_id)
    if not front:
        raise HTTPException(404, "no front image selected")
    return FileResponse(IMAGES_DIR / front["filename"], media_type="image/png")


@app.post("/api/characters/{character_id}/images")
async def upload_character_image(character_id: int, view: str, request: Request):
    if not visible_character(character_id, request.state.owner):
        raise HTTPException(404, "character not found")
    if view not in VIEWS:
        raise HTTPException(400, "unknown view")
    if view != "front" and not selected_front(character_id):
        raise HTTPException(409, "select a front image first")
    filename = await save_upload(request)
    execute("INSERT INTO character_images (character_id, view, filename) VALUES (?, ?, ?)", character_id, view, filename)
    return {"filename": filename}
