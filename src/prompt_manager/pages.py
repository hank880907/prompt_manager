import asyncio
import json
from pathlib import Path

from fastapi.responses import RedirectResponse
from nicegui import app, run, ui

from prompt_manager.auth import add_user, delete_user, is_admin, owner_of, safe_redirect, verify_user
from prompt_manager.comfyui import VIEW_PROMPTS, queued_ids, submit
from prompt_manager.config import CHARACTER_FRONT_WORKFLOW, CHARACTER_VIEW_WORKFLOW, SCENE_WORKFLOW
from prompt_manager.db import (VIEWS, VISIBLE, character_label, execute, execute_many, get, query, scene_labels,
                               selected_front, visible_character, visible_scene)
from prompt_manager.images import image_size, save_png

CONTAINER = "w-full max-w-3xl mx-auto px-4 py-6 gap-3"
ENTER_WITHOUT_IME = "(e) => { if (!e.isComposing && e.keyCode !== 229) emit() }"
ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"]
PROMPT_LABELS = {"image_positive": "图像提示词（正向）", "image_negative": "图像提示词（负向）", "video_prompt": "视频提示词"}
CHARACTER_LABELS = {"positive": "正向提示词", "negative": "负向提示词"}
VIEWER_HEAD = '<link rel="stylesheet" href="/static/photoswipe.css"><script type="module" src="/static/viewer.js"></script>'
UNSAVED_GUARD = "<script>window.addEventListener('beforeunload', e => { if (window.unsavedPrompts) e.preventDefault() })</script>"

CSS = """
body { background: #f6f6f7; color: #18181b;
       font-family: -apple-system, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.q-card { box-shadow: none; border: 1px solid #e4e4e7; border-radius: 12px; }
.q-field--outlined .q-field__control { border-radius: 10px; background: #fff; }
.q-field--outlined .q-field__control:before { border-color: #e4e4e7; }
.q-field--readonly .q-field__control { background: #f4f4f5; color: #71717a; }
div.pswp { --pswp-root-z-index: 5000; }
div.pswp .pswp__button--download, div.pswp .pswp__button--delete { display: flex; align-items: center; justify-content: center; color: #fff; }
.pswp__button--download .material-icons, .pswp__button--delete .material-icons { font-size: 24px; }
.pswp__select { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); display: flex; gap: 6px;
                align-items: center; padding: 8px 18px; border: 0; border-radius: 999px; background: #fff;
                color: #18181b; font-size: 14px; cursor: pointer; }
.pswp__select.selected { background: #21ba45; color: #fff; }
.pswp__select:disabled { cursor: default; }
.pswp__select .material-icons { font-size: 18px; }
.segmented { background: #e4e4e7; border-radius: 10px; padding: 2px; }
.segmented .q-tab { border-radius: 8px; color: #71717a; min-height: 34px; }
.scene-panels, .scene-panels .q-panel { overflow: visible; }
.segmented .q-tab--active { color: #18181b; box-shadow: 0 1px 2px rgb(0 0 0 / 0.08); }
"""

app.add_static_files("/static", Path(__file__).parent / "static")


def style() -> None:
    ui.colors(primary="#18181b")
    ui.add_css(CSS)


def current_user() -> str:
    return app.storage.user.get("username")


def current_owner() -> str:
    return owner_of(current_user())


def logout() -> None:
    app.storage.user.clear()
    ui.navigate.to("/login")


def page_frame(*crumbs: tuple[str, str]) -> None:
    style()
    with ui.header().classes("bg-white text-zinc-900 border-b border-zinc-200 py-3"):
        with ui.row().classes("w-full max-w-3xl mx-auto px-4 items-center no-wrap gap-1"):
            ui.link("提示词管理器", "/").classes("font-semibold no-underline text-zinc-900 shrink-0")
            for name, url in crumbs:
                ui.icon("chevron_right", color="grey-5")
                ui.link(name, url).classes("no-underline text-zinc-500 truncate")
            ui.space()
            username = current_user()
            with ui.button(username, icon="account_circle").props("flat dense no-caps color=grey-8"
                                                                   ).classes("shrink-0 max-w-[40%] truncate"):
                with ui.menu().props("anchor='bottom right' self='top right'"):
                    if is_admin(username):
                        ui.menu_item("用户管理", on_click=lambda: ui.navigate.to("/users"))
                    else:
                        ui.menu_item("修改密码", on_click=lambda: password_dialog(username))
                    ui.menu_item("退出登录", on_click=logout)


def password_dialog(username: str) -> None:
    async def save():
        if not await run.io_bound(verify_user, username, current.value):
            ui.notify("当前密码错误", type="negative")
        elif not new.value:
            ui.notify("请填写新密码", type="warning")
        else:
            await run.io_bound(add_user, username, new.value)
            dialog.close()
            ui.notify("密码已修改", type="positive")

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-sm p-6 gap-4"):
        ui.label("修改密码").classes("text-lg font-semibold")
        current = ui.input("当前密码", password=True).classes("w-full").props("outlined dense autofocus")
        new = ui.input("新密码", password=True, password_toggle_button=True).classes("w-full").props("outlined dense")
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
            ui.button("保存", on_click=save).props("unelevated")
    dialog.open()


def episode_crumbs(episode_id: int) -> list[tuple[str, str]]:
    row = get("SELECT p.id, p.name AS project, e.name AS episode FROM episodes e "
              "JOIN projects p ON p.id = e.project_id WHERE e.id = ?", episode_id)
    return [(row["project"], f"/project/{row['id']}"), (row["episode"], f"/episode/{episode_id}")]


def make_public_dialog(on_confirm) -> None:
    with ui.dialog() as dialog, ui.card().classes("p-6 gap-4"):
        ui.label("设为公开？").classes("text-lg font-semibold")
        ui.label("公开后所有人都能看到和编辑这个项目，且无法再改回私有。").classes("text-zinc-500")
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
            ui.button("设为公开", on_click=lambda: (on_confirm(), ui.navigate.reload())).props("unelevated")
    dialog.open()


def rename_dialog(current: str, on_save) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-sm p-6 gap-4"):
        ui.label("重命名").classes("text-lg font-semibold")
        name = ui.input(value=current).classes("w-full").props("outlined dense autofocus")

        def save():
            if name.value.strip():
                on_save(name.value.strip())
                ui.navigate.reload()

        name.on("keydown.enter", save, js_handler=ENTER_WITHOUT_IME)
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
            ui.button("保存", on_click=save).props("unelevated")
    dialog.open()


def project_dialog(project) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-sm p-6 gap-4"):
        ui.label("编辑项目").classes("text-lg font-semibold")
        name = ui.input("项目名称", value=project["name"]).classes("w-full").props("outlined dense autofocus")
        aspect_ratio = ui.select(ASPECT_RATIOS, label="新场景默认画幅比例", value=project["default_aspect_ratio"]
                                 ).classes("w-full").props("outlined dense")
        if project["owner"] is not None:
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("私有项目，仅自己可见").classes("text-sm text-zinc-500")
                ui.button("设为公开", icon="public", on_click=lambda: make_public_dialog(lambda: execute(
                    "UPDATE projects SET owner = NULL WHERE id = ?", project["id"]))
                          ).props("outline dense no-caps").classes("px-2")

        def save():
            if name.value.strip():
                execute("UPDATE projects SET name = ?, default_aspect_ratio = ? WHERE id = ?",
                        name.value.strip(), aspect_ratio.value, project["id"])
                ui.navigate.reload()

        name.on("keydown.enter", save, js_handler=ENTER_WITHOUT_IME)
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
            ui.button("保存", on_click=save).props("unelevated")
    dialog.open()


def title_row(name: str, on_edit, private: bool = False) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-1"):
        ui.label(name).classes("text-2xl font-semibold truncate")
        if private:
            ui.icon("lock", color="grey-6").tooltip("私有项目")
        ui.button(icon="edit", on_click=on_edit).props("flat round dense color=grey-6")


def section_label(text: str) -> None:
    ui.label(text).classes("text-sm font-medium text-zinc-500 mt-4")


def empty_state(text: str) -> None:
    ui.label(text).classes("w-full text-center text-zinc-400 py-10")


def confirm_delete(name: str, on_confirm) -> None:
    with ui.dialog() as dialog, ui.card().classes("p-6 gap-4"):
        ui.label(f"删除“{name}”？").classes("text-lg font-semibold")
        ui.label("其中的所有内容都会被删除，且无法恢复。").classes("text-zinc-500")
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
            ui.button("删除", color="negative", on_click=lambda: (dialog.close(), on_confirm())).props("unelevated")
    dialog.open()


def add_row(placeholder: str, on_add) -> None:
    with ui.row().classes("w-full no-wrap items-center gap-2"):
        name = ui.input(placeholder=placeholder).classes("grow").props("outlined dense")

        def submit():
            if name.value.strip():
                on_add(name.value.strip())
                name.value = ""

        name.on("keydown.enter", submit, js_handler=ENTER_WITHOUT_IME)
        ui.button("新建", icon="add", on_click=submit).props("unelevated").classes("h-10 rounded-lg")


def item_row(name: str, subtitle: str, url: str, on_delete) -> None:
    with ui.card().classes("w-full p-0 hover:border-zinc-400 transition-colors"):
        with ui.row().classes("w-full no-wrap items-center pr-2"):
            with ui.link(target=url).classes("grow min-w-0 px-4 py-3 no-underline text-zinc-900"):
                ui.label(name).classes("font-medium truncate")
                ui.label(subtitle).classes("text-xs text-zinc-400")
            ui.button(icon="delete_outline", on_click=lambda: confirm_delete(name, on_delete)).props("flat round dense color=grey-6")
            ui.icon("chevron_right", color="grey-5")


@ui.page("/")
def projects_page():
    page_frame()

    @ui.refreshable
    def project_list():
        projects = query(f"SELECT p.*, COUNT(e.id) AS n FROM projects p LEFT JOIN episodes e ON e.project_id = p.id "
                         f"WHERE {VISIBLE} GROUP BY p.id ORDER BY p.id DESC", current_owner(), current_owner())
        if not projects:
            empty_state("还没有项目，点右上角的 + 新建一个吧")
        for p in projects:
            item_row(p["name"], f"{p['n']} 个剧集" + (" · 私有" if p["owner"] is not None else ""), f"/project/{p['id']}",
                     lambda p=p: (execute("DELETE FROM projects WHERE id = ?", p["id"]), project_list.refresh()))

    def new_project_dialog() -> None:
        def create():
            if name.value.strip():
                execute("INSERT INTO projects (name, owner) VALUES (?, ?)",
                        name.value.strip(), current_owner() if private.value else None)
                dialog.close()
                project_list.refresh()

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-sm p-6 gap-4"):
            ui.label("新建项目").classes("text-lg font-semibold")
            name = ui.input(placeholder="项目名称").classes("w-full").props("outlined dense autofocus")
            name.on("keydown.enter", create, js_handler=ENTER_WITHOUT_IME)
            private = ui.checkbox("私有（仅自己可见）").props("dense")
            with ui.row().classes("w-full justify-end"):
                ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
                ui.button("新建", on_click=create).props("unelevated")
        dialog.open()

    with ui.column().classes(CONTAINER):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("项目").classes("text-2xl font-semibold")
            ui.button(icon="add", on_click=new_project_dialog).props("unelevated dense").classes("px-3 rounded-lg").tooltip("新建项目")
        project_list()


@ui.page("/project/{project_id}")
def project_page(project_id: int):
    project = get(f"SELECT * FROM projects p WHERE id = ? AND {VISIBLE}", project_id, current_owner(), current_owner())
    if not project:
        return RedirectResponse("/")
    page_frame((project["name"], f"/project/{project_id}"))

    @ui.refreshable
    def episode_list():
        episodes = query("SELECT e.*, COUNT(s.id) AS n FROM episodes e LEFT JOIN scenes s ON s.episode_id = e.id "
                         "WHERE e.project_id = ? GROUP BY e.id ORDER BY e.id", project_id)
        if not episodes:
            empty_state("还没有剧集")
        for e in episodes:
            item_row(e["name"], f"{e['n']} 个场景", f"/episode/{e['id']}",
                     lambda e=e: (execute("DELETE FROM episodes WHERE id = ?", e["id"]), episode_list.refresh()))

    def add(name):
        execute("INSERT INTO episodes (project_id, name) VALUES (?, ?)", project_id, name)
        episode_list.refresh()

    with ui.column().classes(CONTAINER):
        title_row(project["name"], lambda: project_dialog(project), private=project["owner"] is not None)
        ui.button("角色管理", icon="groups", on_click=lambda: ui.navigate.to(f"/project/{project_id}/characters")
                  ).props("outline no-caps").classes("w-full h-12 rounded-xl")
        section_label("剧集")
        add_row("剧集名称，例如：第 1 集", add)
        episode_list()


def preview(text: str) -> str:
    return text.strip().splitlines()[0][:60] if text.strip() else "（未填写图像提示词）"


@ui.page("/episode/{episode_id}")
def episode_page(episode_id: int):
    episode = get(f"SELECT e.* FROM episodes e JOIN projects p ON p.id = e.project_id WHERE e.id = ? AND {VISIBLE}",
                  episode_id, current_owner(), current_owner())
    if not episode:
        return RedirectResponse("/")
    page_frame(*episode_crumbs(episode_id))

    @ui.refreshable
    def scene_list():
        scenes = query("SELECT s.*, i.filename AS thumbnail, "
                       "(SELECT COUNT(*) FROM images WHERE scene_id = s.id) AS candidates "
                       "FROM scenes s LEFT JOIN images i ON i.id = s.selected_image_id "
                       "WHERE s.episode_id = ? ORDER BY s.position", episode_id)
        if not scenes:
            empty_state("还没有场景")
        with ui.row().classes("w-full no-wrap gap-2"):
            with ui.column().classes("gap-2 shrink-0"):
                for i in range(1, len(scenes) + 1):
                    ui.label(str(i)).classes("h-[76px] w-5 flex items-center justify-end text-xs text-zinc-400 tabular-nums")
            with ui.column().classes("grow min-w-0 gap-2") as container:
                for s in scenes:
                    with ui.card().classes("w-full h-[76px] p-0 hover:border-zinc-400 transition-colors") as card:
                        card.scene_id = s["id"]
                        with ui.row().classes("w-full no-wrap items-center gap-0"):
                            ui.icon("drag_indicator", color="grey-5").classes("drag-handle cursor-grab px-2 py-4 text-xl")
                            with ui.link(target=f"/scene/{s['id']}").classes(
                                    "grow min-w-0 py-2 no-underline text-zinc-900 flex flex-nowrap items-center gap-3"):
                                if s["thumbnail"]:
                                    ui.image(f"/thumbnails/{s['thumbnail']}").props("fit=cover").classes("w-14 h-14 rounded-md shrink-0")
                                else:
                                    with ui.element("div").classes("w-14 h-14 rounded-md shrink-0 bg-zinc-100 flex items-center justify-center"):
                                        ui.icon("image", color="grey-4")
                                with ui.column().classes("min-w-0 gap-0"):
                                    ui.label(s["name"]).classes("font-medium truncate max-w-full")
                                    ui.label(preview(s["image_positive"])).classes("text-xs text-zinc-400 truncate max-w-full")
                            with ui.row().classes("no-wrap items-center gap-1 pl-2 text-xs text-zinc-400 tabular-nums"
                                                  + ("" if s["candidates"] else " opacity-50")):
                                ui.icon("photo_library").classes("text-base")
                                ui.label(str(s["candidates"]))
                            ui.icon("chevron_right", color="grey-5").classes("pr-2")

        def save_order():
            execute_many("UPDATE scenes SET position = ? WHERE id = ?",
                         [(position, card.scene_id) for position, card in enumerate(container.default_slot.children)])

        container.make_sortable({"forceFallback": True}, handle=".drag-handle", on_end=save_order)

    def add():
        position, number = get("SELECT COALESCE(MAX(position), 0) + 1, COUNT(*) + 1 FROM scenes WHERE episode_id = ?",
                               episode_id)
        scene_id = execute("INSERT INTO scenes (episode_id, name, position, aspect_ratio) "
                           "SELECT ?, ?, ?, p.default_aspect_ratio FROM episodes e JOIN projects p ON p.id = e.project_id "
                           "WHERE e.id = ?", episode_id, f"场景 {number}", position, episode_id)
        ui.navigate.to(f"/scene/{scene_id}")

    with ui.column().classes(CONTAINER):
        title_row(episode["name"], lambda: rename_dialog(episode["name"], lambda name: execute(
            "UPDATE episodes SET name = ? WHERE id = ?", name, episode_id)))
        section_label("场景")
        scene_list()
        ui.button("添加场景", icon="add", on_click=add).props("outline").classes("w-full h-12 rounded-xl")


def candidate_count(scene_id: int) -> int:
    return get("SELECT COUNT(*) FROM images WHERE scene_id = ?", scene_id)[0]


def scene_locked(scene_id: int) -> bool:
    return candidate_count(scene_id) + get("SELECT COUNT(*) FROM jobs WHERE scene_id = ?", scene_id)[0] > 0


def lock_notice(text: str, delete_name: str, on_delete, copy_label: str, on_copy) -> ui.column:
    with ui.column().classes("w-full gap-1 mt-3 px-3 pt-2 pb-1 rounded-lg bg-amber-50 text-amber-900 text-xs") as notice:
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.icon("lock", size="16px")
            ui.label(text)
        with ui.row().classes("w-full justify-end gap-1"):
            ui.button(f"删除{delete_name}", icon="delete_sweep", on_click=lambda: confirm_delete(delete_name, on_delete)
                      ).props("flat dense no-caps color=amber-10")
            ui.button(copy_label, icon="content_copy", on_click=on_copy).props("flat dense no-caps color=amber-10")
    return notice


async def start_job(workflow: str, inputs: dict[str, dict], **job) -> bool:
    try:
        prompt_id = await run.io_bound(submit, workflow, inputs)
    except (OSError, RuntimeError) as error:
        ui.notify(f"无法提交到 ComfyUI：{error}", type="negative", multi_line=True)
        return False
    execute(f"INSERT INTO jobs (prompt_id, {', '.join(job)}) VALUES (?{', ?' * len(job)})", prompt_id, *job.values())
    return True


async def sync_jobs() -> None:
    """Drop jobs that ComfyUI has finished, or all of them if ComfyUI can't be reached."""
    jobs = [row["prompt_id"] for row in query("SELECT prompt_id FROM jobs")]
    if jobs:
        queued = await run.io_bound(queued_ids) or set()
        execute_many("DELETE FROM jobs WHERE prompt_id = ?", [(job,) for job in jobs if job not in queued])


def candidate_gallery(event: str, title: str, empty_text: str, load, select, delete,
                      on_count=lambda count: None, selection_locked=lambda: False, fit: str = "cover",
                      notice=lambda: None, pending=lambda: 0):
    """load() returns rows with id, filename and selected; notice() renders under the title;
    pending() is the number of images still being generated. Needs VIEWER_HEAD on the page."""
    shown = (0, 0)

    @ui.refreshable
    def gallery():
        nonlocal shown
        images = load()
        shown = (len(images), pending())
        on_count(sum(shown))
        section_label(f"{title}（{len(images)}）")
        notice()
        if not any(shown):
            empty_state(empty_text)
            return
        ui.label("点击图片可放大查看、选用或删除").classes("text-xs text-zinc-400")
        with ui.element("div").classes("grid grid-cols-2 sm:grid-cols-3 gap-2 w-full"):
            for _ in range(shown[1]):
                with ui.element("div").classes("aspect-square rounded-lg bg-zinc-200 flex items-center justify-center"):
                    ui.spinner(size="lg", color="grey-6")
            for i, img in enumerate(images):
                with ui.element("div").classes("relative cursor-pointer").on(
                        "click", lambda i=i: open_viewer(list(images), i)):
                    ui.image(f"/thumbnails/{img['filename']}").props(f"fit={fit}").classes(
                        "aspect-square rounded-lg bg-zinc-200" + (" ring-4 ring-zinc-900" if img["selected"] else ""))
                    if img["selected"]:
                        ui.badge("已选用", color="positive").classes("absolute top-2 left-2")

    def open_viewer(images: list, index: int) -> None:
        items = [{"id": img["id"], "filename": img["filename"], "src": f"/previews/{img['filename']}",
                  "msrc": f"/thumbnails/{img['filename']}", **dict(zip(("width", "height"), image_size(img["filename"])))}
                 for img in images]
        selected_id = next((img["id"] for img in images if img["selected"]), None)
        ui.run_javascript(f"openViewer({json.dumps(items)}, {index}, {json.dumps(selected_id)}, "
                          f"{json.dumps(event)}, {json.dumps(selection_locked())})")

    def on_select(image_id: int | None) -> None:
        if not selection_locked():
            select(image_id)

    def on_delete(image_id: int) -> None:
        if selection_locked() and any(img["id"] == image_id and img["selected"] for img in load()):
            ui.notify("选用的图片已锁定，无法删除", type="warning")
            return
        delete(image_id)
        ui.run_javascript(f"viewerRemove({image_id})")

    ui.on(f"{event}_select", lambda e: on_select(e.args))
    ui.on(f"{event}_delete", lambda e: confirm_delete("这张候选图", lambda: on_delete(e.args)))
    ui.on(f"{event}_closed", gallery.refresh)
    gallery()
    ui.timer(5, lambda: (len(load()), pending()) != shown and gallery.refresh())
    return gallery.refresh


def scene_editor(scene) -> None:
    columns = (*PROMPT_LABELS, "aspect_ratio")
    locked_columns = ("image_positive", "image_negative", "aspect_ratio")
    saved = {column: scene[column] for column in columns}
    fields = {}
    save_buttons = []
    locked = scene_locked(scene["id"])

    def set_unsaved(unsaved: bool) -> None:
        if unsaved != save_buttons[0].enabled:
            for button in save_buttons:
                button.set_enabled(unsaved)
            ui.run_javascript(f"window.unsavedPrompts = {str(unsaved).lower()}")

    def on_edit() -> None:
        set_unsaved(any(fields[c].value != saved[c] for c in columns))

    def set_locked(value: bool) -> None:
        notice.set_visibility(value)
        for column in locked_columns:
            if value:
                fields[column].props("readonly")
            else:
                fields[column].props(remove="readonly")

    def unlock_when_empty(count: int) -> None:
        if count == 0:
            set_locked(False)

    async def generate() -> None:
        if save_buttons[0].enabled:
            save()
        label = next(s["label"] for s in scene_labels(current_owner()) if s["id"] == scene["id"])
        if await start_job(SCENE_WORKFLOW, {"PromptManagerLoadScene": {"scene": label}}, scene_id=scene["id"]):
            set_locked(True)
            refresh_gallery()

    def copy_scene() -> None:
        execute("UPDATE scenes SET position = position + 1 WHERE episode_id = ? AND position > ?",
                scene["episode_id"], scene["position"])
        scene_id = execute("INSERT INTO scenes (episode_id, name, position, image_positive, image_negative, video_prompt, "
                           "aspect_ratio) SELECT episode_id, name || ' 副本', position + 1, image_positive, image_negative, "
                           "video_prompt, aspect_ratio FROM scenes WHERE id = ?", scene["id"])
        ui.navigate.to(f"/scene/{scene_id}")

    def delete_candidates() -> None:
        execute("DELETE FROM images WHERE scene_id = ?", scene["id"])
        refresh_gallery()

    def save() -> None:
        if any(fields[c].value != saved[c] for c in locked_columns) and scene_locked(scene["id"]):
            ui.notify("已有或正在生成候选图，图像提示词和画幅比例无法保存。可先复制文字，刷新后用“复制场景”新建场景再粘贴。",
                      type="warning")
            return
        saved.update({c: fields[c].value for c in columns})
        execute("UPDATE scenes SET image_positive = ?, image_negative = ?, video_prompt = ?, aspect_ratio = ? WHERE id = ?",
                *saved.values(), scene["id"])
        set_unsaved(False)
        ui.notify("已保存", type="positive")

    def prompt_fields(*columns: str) -> None:
        for i, column in enumerate(columns):
            with ui.row().classes("w-full items-end justify-between no-wrap mt-2"):
                ui.label(PROMPT_LABELS[column]).classes("text-xs font-medium text-zinc-500")
                if i == 0:
                    save_buttons.append(ui.button("保存", icon="save", on_click=save).props("unelevated dense")
                                        .classes("px-3 rounded-lg"))
                    save_buttons[-1].disable()
            fields[column] = ui.textarea(value=scene[column], on_change=on_edit).classes("w-full").props("outlined autogrow")
            if locked and column in locked_columns:
                fields[column].props("readonly")

    ui.add_body_html(UNSAVED_GUARD)

    with ui.row().classes("w-full items-center justify-between no-wrap mt-3"):
        ui.label("画幅比例").classes("text-xs font-medium text-zinc-500")
        fields["aspect_ratio"] = ui.select(ASPECT_RATIOS, value=scene["aspect_ratio"], on_change=on_edit
                                           ).classes("w-28").props("outlined dense options-dense")
        if locked:
            fields["aspect_ratio"].props("readonly")

    with ui.tabs().props("dense no-caps inline-label align=justify active-bg-color=white indicator-color=transparent"
                         ).classes("segmented w-full mt-3") as tabs:
        image_tab = ui.tab("图像", icon="image")
        video_tab = ui.tab("视频", icon="movie")
    with ui.tab_panels(tabs, value=image_tab).props("transition-prev=fade transition-next=fade transition-duration=150"
                                                   ).classes("scene-panels w-full bg-transparent"):
        with ui.tab_panel(image_tab).classes("p-0 gap-1"):
            notice = lock_notice("已有或正在生成候选图，图像提示词和画幅比例不可编辑。如需修改，请删除全部候选图，或复制场景。",
                                 "全部候选图", delete_candidates, "复制场景", copy_scene)
            notice.set_visibility(locked)
            prompt_fields("image_positive", "image_negative")
            if SCENE_WORKFLOW:
                ui.button("生成候选图", icon="auto_awesome", on_click=generate).props("unelevated no-caps").classes(
                    "w-full mt-3 rounded-lg")
            ui.timer(3, sync_jobs)
            refresh_gallery = candidate_gallery(
                "scene", "候选图", "还没有候选图，在 ComfyUI 中用“保存候选图”节点生成",
                lambda: query("SELECT i.id, i.filename, i.id = s.selected_image_id AS selected FROM images i "
                              "JOIN scenes s ON s.id = i.scene_id WHERE i.scene_id = ? ORDER BY i.id DESC", scene["id"]),
                lambda image_id: execute("UPDATE scenes SET selected_image_id = ? WHERE id = ?", image_id, scene["id"]),
                lambda image_id: execute("DELETE FROM images WHERE id = ?", image_id),
                on_count=unlock_when_empty,
                pending=lambda: get("SELECT COUNT(*) FROM jobs WHERE scene_id = ?", scene["id"])[0])
        with ui.tab_panel(video_tab).classes("p-0 gap-1"):
            prompt_fields("video_prompt")


@ui.page("/scene/{scene_id}")
def scene_page(scene_id: int):
    scene = visible_scene(scene_id, current_owner(), "s.*")
    if not scene:
        return RedirectResponse("/")
    episode_url = f"/episode/{scene['episode_id']}"
    page_frame(*episode_crumbs(scene["episode_id"]))
    ui.add_head_html(VIEWER_HEAD)

    def delete():
        execute("DELETE FROM scenes WHERE id = ?", scene_id)
        ui.navigate.to(episode_url)

    with ui.column().classes(CONTAINER + " gap-1"):
        ui.button("返回场景列表", icon="arrow_back", on_click=lambda: ui.navigate.to(episode_url)
                  ).props("flat dense color=grey-8 no-caps").classes("-ml-2")
        title_row(scene["name"], lambda: rename_dialog(scene["name"], lambda name: execute(
            "UPDATE scenes SET name = ? WHERE id = ?", name, scene_id)))
        scene_editor(scene)
        ui.button("删除场景", icon="delete_outline", on_click=lambda: confirm_delete(scene["name"], delete)
                  ).props("flat dense color=grey-7 no-caps").classes("self-end mt-4")


@ui.page("/project/{project_id}/characters")
def characters_page(project_id: int):
    project = get(f"SELECT * FROM projects p WHERE id = ? AND {VISIBLE}", project_id, current_owner(), current_owner())
    if not project:
        return RedirectResponse("/")
    page_frame((project["name"], f"/project/{project_id}"), ("角色", f"/project/{project_id}/characters"))

    @ui.refreshable
    def character_list():
        characters = query(
            "SELECT c.id, c.name, COUNT(i.id) AS n, "
            "MAX(CASE WHEN i.view = 'front' AND i.selected THEN i.filename END) AS thumbnail, "
            "COUNT(DISTINCT CASE WHEN i.view != 'front' THEN i.view END) AS views "
            "FROM characters c LEFT JOIN character_images i ON i.character_id = c.id "
            "WHERE c.project_id = ? GROUP BY c.id ORDER BY c.id", project_id)
        if not characters:
            empty_state("还没有角色")
        total_views = len(VIEWS) - 1
        for c in characters:
            def delete(c=c):
                execute("DELETE FROM characters WHERE id = ?", c["id"])
                character_list.refresh()

            with ui.card().classes("w-full p-0 hover:border-zinc-400 transition-colors"):
                with ui.row().classes("w-full no-wrap items-center pr-2"):
                    with ui.link(target=f"/character/{c['id']}").classes(
                            "grow min-w-0 p-2 no-underline text-zinc-900 flex flex-nowrap items-center gap-3"):
                        if c["thumbnail"]:
                            ui.image(f"/thumbnails/{c['thumbnail']}").props("fit=cover").classes("w-12 h-16 rounded-md shrink-0")
                        else:
                            with ui.element("div").classes("w-12 h-16 rounded-md shrink-0 bg-zinc-100 flex items-center justify-center"):
                                ui.icon("person_outline", color="grey-4")
                        with ui.column().classes("min-w-0 gap-0"):
                            ui.label(c["name"]).classes("font-medium truncate max-w-full")
                            ui.label(f"#{c['id']} · {c['n']} 张图").classes("text-xs text-zinc-400")
                            if not c["thumbnail"]:
                                status, color = "未选正面图", "bg-zinc-100 text-zinc-500"
                            elif c["views"] == total_views:
                                status, color = "多视角完成", "bg-green-100 text-green-700"
                            else:
                                status, color = f"多视角 {c['views']}/{total_views}", "bg-zinc-100 text-zinc-500"
                            ui.label(status).classes(f"text-[11px] px-2 py-0.5 mt-1.5 rounded-full {color}")
                    ui.button(icon="delete_outline", on_click=lambda c=c, delete=delete: confirm_delete(c["name"], delete)
                              ).props("flat round dense color=grey-6")
                    ui.icon("chevron_right", color="grey-5")

    def add(name):
        character_id = execute("INSERT INTO characters (project_id, name) VALUES (?, ?)", project_id, name)
        ui.navigate.to(f"/character/{character_id}")

    with ui.column().classes(CONTAINER):
        ui.label("角色管理").classes("text-2xl font-semibold")
        add_row("角色名称", add)
        character_list()


def view_count(character_id: int, front: bool) -> int:
    return get("SELECT COUNT(*) FROM character_images WHERE character_id = ? AND (view = 'front') = ?",
               character_id, front)[0]


def pending_count(character_id: int, front: bool) -> int:
    return get("SELECT COUNT(*) FROM jobs WHERE character_id = ? AND (view = 'front') = ?", character_id, front)[0]


def prompts_locked(character_id: int) -> bool:
    return view_count(character_id, front=True) + pending_count(character_id, front=True) > 0


def front_selection_locked(character_id: int) -> bool:
    return view_count(character_id, front=False) + pending_count(character_id, front=False) > 0


def character_editor(character) -> None:
    character_id = character["id"]
    saved = {column: character[column] for column in CHARACTER_LABELS}
    fields = {}
    locked = prompts_locked(character_id)

    def on_edit() -> None:
        unsaved = any(fields[c].value != saved[c] for c in CHARACTER_LABELS)
        if unsaved != save_button.enabled:
            save_button.set_enabled(unsaved)
            ui.run_javascript(f"window.unsavedPrompts = {str(unsaved).lower()}")

    def save() -> None:
        if prompts_locked(character_id):
            ui.notify("已有或正在生成正面全身图，提示词无法保存。可先复制文字，刷新后用“复制角色”新建角色再粘贴。", type="warning")
            return
        saved.update({c: fields[c].value for c in CHARACTER_LABELS})
        execute("UPDATE characters SET positive = ?, negative = ? WHERE id = ?", *saved.values(), character_id)
        on_edit()
        ui.notify("已保存", type="positive")

    def set_locked(value: bool) -> None:
        notice.set_visibility(value)
        for field in fields.values():
            if value:
                field.props("readonly")
            else:
                field.props(remove="readonly")
        references.refresh()

    def unlock_when_empty(count: int) -> None:
        if count == 0:
            set_locked(False)

    async def generate(view: str) -> bool:
        if view == "front" and save_button.enabled:
            save()
        label = character_label(visible_character(character_id, current_owner(), "c.id, c.name, p.name AS project"))
        inputs = {node: {"character": label} for node in (
            "PromptManagerLoadCharacter", "PromptManagerLoadCharacterReference", "PromptManagerLoadCharacterUploads")}
        inputs["PromptManagerSaveCharacterImage"] = {"view": VIEW_PROMPTS[view]}
        if view != "front":
            inputs["PromptManagerLoadCharacterReference"]["view"] = VIEW_PROMPTS[view]
        workflow = CHARACTER_FRONT_WORKFLOW if view == "front" else CHARACTER_VIEW_WORKFLOW
        if not await start_job(workflow, inputs, character_id=character_id, view=view):
            return False
        if view == "front":
            set_locked(True)
        else:
            refresh_views[view]()
        refresh_front()
        return True

    async def generate_views() -> None:
        if not selected_front(character_id):
            ui.notify("请先选用一张正面全身图", type="warning")
            return
        for view in refresh_views:
            if not await generate(view):
                return

    async def add_references(e) -> None:
        uploader.reset()
        if prompts_locked(character_id):
            ui.notify("已有或正在生成正面全身图，参考图无法修改", type="warning")
            return
        for file in e.files:
            filename = await run.io_bound(save_png, await file.read())
            execute("INSERT INTO character_references (character_id, filename) VALUES (?, ?)", character_id, filename)
        references.refresh()

    def delete_reference(reference_id: int) -> None:
        if prompts_locked(character_id):
            ui.notify("已有或正在生成正面全身图，参考图无法修改", type="warning")
            return
        execute("DELETE FROM character_references WHERE id = ?", reference_id)
        references.refresh()

    @ui.refreshable
    def references() -> None:
        rows = query("SELECT id, filename FROM character_references WHERE character_id = ? ORDER BY id", character_id)
        editable = not prompts_locked(character_id)
        with ui.expansion(value=True).classes("w-full bg-white border border-zinc-200 rounded-xl mt-3") as expansion:
            with expansion.add_slot("header"):
                with ui.row().classes("w-full items-center no-wrap gap-3"):
                    ui.label("参考图").classes("font-semibold")
                    with ui.row().classes("no-wrap gap-0 -space-x-2"):
                        for row in rows[:4]:
                            ui.image(f"/thumbnails/{row['filename']}").classes("w-7 h-7 rounded-full ring-2 ring-white")
                    ui.label(f"{len(rows)} 张").classes("text-xs text-zinc-400")
            with ui.column().classes("w-full gap-3 pb-2"):
                if editable:
                    with ui.button(on_click=lambda: uploader.run_method("pickFiles")).props("flat no-caps").classes(
                            "w-full py-4 border-2 border-dashed border-zinc-300 rounded-lg text-zinc-400"):
                        ui.icon("add_photo_alternate")
                        ui.label("点击上传图片（可多选）").classes("ml-2")
                elif not rows:
                    ui.label("没有参考图").classes("text-sm text-zinc-400")
                with ui.element("div").classes("grid grid-cols-4 sm:grid-cols-6 gap-2 w-full"):
                    for row in rows:
                        with ui.element("div").classes("relative"):
                            ui.image(f"/thumbnails/{row['filename']}").classes("aspect-square rounded-lg bg-zinc-200")
                            if editable:
                                ui.button(icon="close", on_click=lambda r=row["id"]: confirm_delete(
                                    "这张参考图", lambda: delete_reference(r))).props(
                                    "round dense size=xs color=black").classes("absolute top-1 right-1 opacity-60")

    def delete_front() -> None:
        if front_selection_locked(character_id):
            ui.notify("已有或正在生成其他视角的图片，请先删除它们", type="warning")
            return
        execute("DELETE FROM character_images WHERE character_id = ? AND view = 'front'", character_id)
        refresh_front()

    def delete_views() -> None:
        execute("DELETE FROM character_images WHERE character_id = ? AND view != 'front'", character_id)
        for refresh in refresh_views.values():
            refresh()

    def front_notice() -> None:
        nonlocal front_locked
        front_locked = front_selection_locked(character_id)
        if front_locked:
            lock_notice("已有或正在生成多视角图片，正面全身图的选用已锁定。如需更换，请删除全部多视角图片，或复制角色。",
                        "全部多视角图片", delete_views, "复制角色", copy_character)

    def on_view_count(count: int) -> None:
        if front_selection_locked(character_id) != front_locked:
            refresh_front()

    def copy_character() -> None:
        copy_id = execute("INSERT INTO characters (project_id, name, positive, negative) "
                          "SELECT project_id, name || ' 副本', positive, negative FROM characters WHERE id = ?", character_id)
        execute("INSERT INTO character_references (character_id, filename) "
                "SELECT ?, filename FROM character_references WHERE character_id = ?", copy_id, character_id)
        ui.navigate.to(f"/character/{copy_id}")

    def view_gallery(view: str, **options):
        return candidate_gallery(
            view, VIEWS[view], "还没有图片",
            lambda: query("SELECT id, filename, selected FROM character_images "
                          "WHERE character_id = ? AND view = ? ORDER BY id DESC", character_id, view),
            lambda image_id: execute("UPDATE character_images SET selected = (id IS ?) WHERE character_id = ? AND view = ?",
                                     image_id, character_id, view),
            lambda image_id: execute("DELETE FROM character_images WHERE id = ?", image_id),
            pending=lambda: get("SELECT COUNT(*) FROM jobs WHERE character_id = ? AND view = ?", character_id, view)[0],
            fit="contain", **options)

    ui.add_body_html(UNSAVED_GUARD)
    notice = lock_notice("已有或正在生成正面全身图，参考图和提示词不可编辑。如需修改，请删除全部正面全身图，或复制角色。",
                         "全部正面全身图", delete_front, "复制角色", copy_character)
    notice.set_visibility(locked)
    uploader = ui.upload(multiple=True, auto_upload=True, on_multi_upload=add_references
                         ).props("accept=image/*").classes("hidden")
    references()
    for i, (column, label) in enumerate(CHARACTER_LABELS.items()):
        with ui.row().classes("w-full items-end justify-between no-wrap mt-2"):
            ui.label(label).classes("text-xs font-medium text-zinc-500")
            if i == 0:
                save_button = ui.button("保存", icon="save", on_click=save).props("unelevated dense").classes("px-3 rounded-lg")
                save_button.disable()
        fields[column] = ui.textarea(value=character[column], on_change=on_edit).classes("w-full").props("outlined autogrow")
        if locked:
            fields[column].props("readonly")
    if CHARACTER_FRONT_WORKFLOW:
        ui.button("生成正面全身图", icon="auto_awesome", on_click=lambda: generate("front")).props(
            "unelevated no-caps").classes("w-full mt-3 rounded-lg")
    ui.timer(3, sync_jobs)
    front_locked = False
    refresh_front = view_gallery("front", on_count=unlock_when_empty, notice=front_notice,
                                 selection_locked=lambda: front_selection_locked(character_id))
    ui.label("多视角").classes("text-lg font-semibold mt-6")
    ui.label("选用一张正面全身图后，在 ComfyUI 中用“加载角色参考图”生成以下视角。生成后正面全身图的选用会被锁定。"
             ).classes("text-xs text-zinc-400")
    if CHARACTER_VIEW_WORKFLOW:
        ui.button("生成全部视角", icon="auto_awesome", on_click=generate_views).props("unelevated no-caps").classes(
            "w-full mt-3 rounded-lg")
    refresh_views = {view: view_gallery(view, on_count=on_view_count) for view in list(VIEWS)[1:]}


@ui.page("/character/{character_id}")
def character_page(character_id: int):
    character = visible_character(character_id, current_owner(), "c.*, p.name AS project")
    if not character:
        return RedirectResponse("/")
    list_url = f"/project/{character['project_id']}/characters"
    page_frame((character["project"], f"/project/{character['project_id']}"), ("角色", list_url))
    ui.add_head_html(VIEWER_HEAD)

    def delete():
        execute("DELETE FROM characters WHERE id = ?", character_id)
        ui.navigate.to(list_url)

    with ui.column().classes(CONTAINER + " gap-1"):
        ui.button("返回角色列表", icon="arrow_back", on_click=lambda: ui.navigate.to(list_url)
                  ).props("flat dense color=grey-8 no-caps").classes("-ml-2")
        title_row(character["name"], lambda: rename_dialog(character["name"], lambda name: execute(
            "UPDATE characters SET name = ? WHERE id = ?", name, character_id)))
        ui.label(f"角色 ID：{character_id}").classes("text-xs text-zinc-400")
        character_editor(character)
        ui.button("删除角色", icon="delete_outline", on_click=lambda: confirm_delete(character["name"], delete)
                  ).props("flat dense color=grey-7 no-caps").classes("self-end mt-4")


@ui.page("/users")
def users_page():
    if not is_admin(current_user()):
        ui.navigate.to("/")
        return
    page_frame(("用户管理", "/users"))

    @ui.refreshable
    def user_list():
        users = query("SELECT username FROM users ORDER BY username")
        if not users:
            empty_state("还没有其他用户")
        for u in users:
            with ui.card().classes("w-full p-0"):
                with ui.row().classes("w-full no-wrap items-center px-4 py-2"):
                    ui.label(u["username"]).classes("grow font-medium truncate")
                    ui.button(icon="delete_outline", on_click=lambda name=u["username"]: confirm_delete(
                        name, lambda: (delete_user(name), user_list.refresh()))
                              ).props("flat round dense color=grey-6")

    async def save():
        name = username.value.strip()
        if not name or not password.value:
            ui.notify("请填写用户名和密码", type="warning")
        elif is_admin(name):
            ui.notify("不能使用管理员的用户名", type="warning")
        else:
            await run.io_bound(add_user, name, password.value)
            ui.notify(f"已保存用户 {name}", type="positive")
            username.value = password.value = ""
            user_list.refresh()

    with ui.column().classes(CONTAINER):
        ui.label("用户管理").classes("text-2xl font-semibold")
        with ui.card().classes("w-full p-4 gap-2"):
            username = ui.input("用户名").classes("w-full").props("outlined dense")
            password = ui.input("密码", password=True, password_toggle_button=True).classes("w-full").props("outlined dense")
            ui.label("填写已有用户名会重置该用户的密码").classes("text-xs text-zinc-400")
            ui.button("保存用户", icon="person_add", on_click=save).props("unelevated").classes("w-full rounded-lg")
        section_label("用户")
        user_list()


@ui.page("/login")
def login_page(redirect_to: str = "/"):
    style()

    async def try_login():
        if await run.io_bound(verify_user, username.value, password.value):
            app.storage.user["username"] = username.value
            ui.navigate.to(safe_redirect(redirect_to))
        else:
            await asyncio.sleep(1)
            ui.notify("用户名或密码错误", type="negative")

    with ui.card().classes("w-full max-w-sm mx-auto mt-24 p-6 gap-4"):
        ui.label("提示词管理器").classes("text-2xl font-semibold")
        username = ui.input("用户名").classes("w-full").props("outlined autofocus")
        password = ui.input("密码", password=True, password_toggle_button=True).classes("w-full").props("outlined")
        password.on("keydown.enter", try_login, js_handler=ENTER_WITHOUT_IME)
        ui.button("登录", on_click=try_login).props("unelevated").classes("w-full h-11 rounded-lg")
