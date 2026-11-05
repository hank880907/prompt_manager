from uuid import uuid4

from fastapi import HTTPException, Request
from nicegui import app, run

from prompt_manager.config import IMAGES_DIR
from prompt_manager.db import execute, get, query


@app.get("/api/scenes")
async def list_scenes():
    rows = query("""
        SELECT s.id, p.name AS project, e.name AS episode, s.name,
               ROW_NUMBER() OVER (PARTITION BY s.episode_id ORDER BY s.position) AS n
        FROM scenes s JOIN episodes e ON e.id = s.episode_id JOIN projects p ON p.id = e.project_id
        ORDER BY p.id, e.id, s.position
    """)
    return [{"id": r["id"], "label": f"{r['project']} / {r['episode']} / {r['n']}. {r['name']} #{r['id']}"}
            for r in rows]


@app.get("/api/scenes/{scene_id}")
async def get_scene(scene_id: int):
    scene = get("SELECT image_positive, image_negative, video_prompt FROM scenes WHERE id = ?", scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    return dict(scene)


@app.post("/api/scenes/{scene_id}/images")
async def upload_image(scene_id: int, request: Request):
    if not get("SELECT id FROM scenes WHERE id = ?", scene_id):
        raise HTTPException(404, "scene not found")
    filename = f"{uuid4().hex}.png"
    await run.io_bound((IMAGES_DIR / filename).write_bytes, await request.body())
    execute("INSERT INTO images (scene_id, filename) VALUES (?, ?)", scene_id, filename)
    return {"filename": filename}
