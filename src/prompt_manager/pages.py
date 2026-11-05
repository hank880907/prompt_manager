import asyncio

from fastapi.responses import RedirectResponse
from nicegui import app, run, ui

from prompt_manager.auth import add_user, delete_user, is_admin, owner_of, safe_redirect, verify_user
from prompt_manager.db import VISIBLE, execute, execute_many, get, query, visible_scene

CONTAINER = "w-full max-w-3xl mx-auto px-4 py-6 gap-3"
ENTER_WITHOUT_IME = "(e) => { if (!e.isComposing && e.keyCode !== 229) emit() }"
PROMPT_LABELS = {"image_positive": "图像提示词（正向）", "image_negative": "图像提示词（负向）", "video_prompt": "视频提示词"}

CSS = """
body { background: #f6f6f7; color: #18181b;
       font-family: -apple-system, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.q-card { box-shadow: none; border: 1px solid #e4e4e7; border-radius: 12px; }
.q-field--outlined .q-field__control { border-radius: 10px; background: #fff; }
.q-field--outlined .q-field__control:before { border-color: #e4e4e7; }
.q-field--readonly .q-field__control { background: #f4f4f5; color: #71717a; }
.viewer-track { scrollbar-width: none; overscroll-behavior-x: contain; opacity: 0; }
.viewer-track::-webkit-scrollbar { display: none; }
.segmented { background: #e4e4e7; border-radius: 10px; padding: 2px; }
.segmented .q-tab { border-radius: 8px; color: #71717a; min-height: 34px; }
.scene-panels, .scene-panels .q-panel { overflow: visible; }
.segmented .q-tab--active { color: #18181b; box-shadow: 0 1px 2px rgb(0 0 0 / 0.08); }
"""
SWIPE_INDEX_JS = """(e) => {
    const i = String(Math.round(e.target.scrollLeft / e.target.clientWidth));
    if (i !== e.target.dataset.index) { e.target.dataset.index = i; emit(Number(i)); }
}"""


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


def rename_dialog(current: str, on_save, on_make_public=None) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-sm p-6 gap-4"):
        ui.label("编辑项目" if on_make_public else "重命名").classes("text-lg font-semibold")
        name = ui.input(value=current).classes("w-full").props("outlined dense autofocus")
        if on_make_public:
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("私有项目，仅自己可见").classes("text-sm text-zinc-500")
                ui.button("设为公开", icon="public", on_click=lambda: make_public_dialog(on_make_public)
                          ).props("outline dense no-caps").classes("px-2")

        def save():
            if name.value.strip():
                on_save(name.value.strip())
                ui.navigate.reload()

        name.on("keydown.enter", save, js_handler=ENTER_WITHOUT_IME)
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=dialog.close).props("flat color=grey-8")
            ui.button("保存", on_click=save).props("unelevated")
    dialog.open()


def title_row(name: str, on_rename, on_make_public=None) -> None:
    """Pass `on_make_public` for a private project: shows a lock and a make-public button when editing."""
    with ui.row().classes("w-full items-center no-wrap gap-1"):
        ui.label(name).classes("text-2xl font-semibold truncate")
        if on_make_public:
            ui.icon("lock", color="grey-6").tooltip("私有项目")
        ui.button(icon="edit", on_click=lambda: rename_dialog(name, on_rename, on_make_public)).props("flat round dense color=grey-6")


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
        title_row(project["name"], lambda name: execute("UPDATE projects SET name = ? WHERE id = ?", name, project_id),
                  on_make_public=None if project["owner"] is None else (
                      lambda: execute("UPDATE projects SET owner = NULL WHERE id = ?", project_id)))
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
        scene_id = execute("INSERT INTO scenes (episode_id, name, position) VALUES (?, ?, ?)",
                           episode_id, f"场景 {number}", position)
        ui.navigate.to(f"/scene/{scene_id}")

    with ui.column().classes(CONTAINER):
        title_row(episode["name"], lambda name: execute("UPDATE episodes SET name = ? WHERE id = ?", name, episode_id))
        section_label("场景")
        scene_list()
        ui.button("添加场景", icon="add", on_click=add).props("outline").classes("w-full h-12 rounded-xl")


def selected_image_id(scene_id: int) -> int | None:
    return get("SELECT selected_image_id FROM scenes WHERE id = ?", scene_id)[0]


def image_viewer(scene_id: int, images: list, index: int, on_close) -> None:
    def on_swipe(e) -> None:
        nonlocal index
        index = min(e.args, len(images) - 1)
        update()

    def go(target: int, smooth: bool = True) -> None:
        target = max(0, min(target, len(images) - 1))
        ui.run_javascript(f"const el = getHtmlElement({track.id}); el.style.opacity = 1; "
                          f"el.scrollTo({{left: {target} * el.clientWidth, behavior: '{'smooth' if smooth else 'instant'}'}})")

    def on_key(e) -> None:
        if dialog.value and e.action.keydown and (e.key.arrow_left or e.key.arrow_right):
            go(index + (-1 if e.key.arrow_left else 1))

    def update() -> None:
        counter.text = f"{index + 1} / {len(images)}"
        selected = selected_image_id(scene_id) == images[index]["id"]
        select_button.text = "已选用" if selected else "选用"
        select_button.props(f"icon={'check_circle' if selected else 'radio_button_unchecked'} "
                            f"color={'positive' if selected else 'white'} text-color={'white' if selected else 'black'}")

    def toggle_selected() -> None:
        image_id = images[index]["id"]
        execute("UPDATE scenes SET selected_image_id = CASE WHEN selected_image_id = ? THEN NULL ELSE ? END "
                "WHERE id = ?", image_id, image_id, scene_id)
        update()

    def delete() -> None:
        nonlocal index
        execute("DELETE FROM images WHERE id = ?", images.pop(index)["id"])
        slides.pop(index).delete()
        if images:
            index = min(index, len(images) - 1)
            update()
        else:
            dialog.close()

    with ui.dialog().props("maximized").on("hide", on_close) as dialog, \
            ui.card().classes("w-full h-full bg-black p-0 gap-0 rounded-none"):
        with ui.row().classes("w-full justify-between items-center no-wrap px-2 py-2"):
            ui.button(icon="close", on_click=dialog.close).props("flat round color=white")
            counter = ui.label().classes("text-white text-sm")
            with ui.row().classes("no-wrap gap-1"):
                ui.button(icon="download", on_click=lambda: ui.download(f"/images/{images[index]['filename']}")
                          ).props("flat round color=white").tooltip("下载原图 PNG")
                ui.button("删除", icon="delete_outline", on_click=lambda: confirm_delete(f"候选图 {index + 1}", delete)
                          ).props("flat dense color=white no-caps")
        with ui.element("div").classes(
                "viewer-track w-full grow min-h-0 flex flex-nowrap overflow-x-auto snap-x snap-mandatory") as track:
            slides = [ui.image(f"/previews/{img['filename']}")
                      .props(f"fit=contain placeholder-src=/thumbnails/{img['filename']}")
                      .classes("w-full h-full shrink-0 snap-center snap-always") for img in images]
        with ui.row().classes("w-full justify-between items-center no-wrap px-2 py-3"):
            ui.button(icon="chevron_left", on_click=lambda: go(index - 1)).props("flat round color=white size=lg")
            select_button = ui.button(on_click=toggle_selected).props("rounded unelevated no-caps")
            ui.button(icon="chevron_right", on_click=lambda: go(index + 1)).props("flat round color=white size=lg")
        ui.keyboard(on_key=on_key, ignore=["input", "textarea"])

    track.on("scroll", on_swipe, js_handler=SWIPE_INDEX_JS)
    dialog.on("show", lambda: go(index, smooth=False))
    update()
    dialog.open()


def candidate_count(scene_id: int) -> int:
    return get("SELECT COUNT(*) FROM images WHERE scene_id = ?", scene_id)[0]


def candidate_gallery(scene_id: int, on_count):
    shown = 0

    @ui.refreshable
    def gallery():
        nonlocal shown
        images = query("SELECT * FROM images WHERE scene_id = ? ORDER BY id DESC", scene_id)
        selected_id = selected_image_id(scene_id)
        shown = len(images)
        on_count(shown)
        section_label(f"候选图（{len(images)}）")
        if not images:
            empty_state("还没有候选图，在 ComfyUI 中用“保存候选图”节点生成")
            return
        ui.label("点击图片可放大查看、选用或删除").classes("text-xs text-zinc-400")
        with ui.element("div").classes("grid grid-cols-2 sm:grid-cols-3 gap-2 w-full"):
            for i, img in enumerate(images):
                selected = img["id"] == selected_id
                with ui.element("div").classes("relative cursor-pointer").on(
                        "click", lambda i=i: open_viewer(list(images), i)):
                    ui.image(f"/thumbnails/{img['filename']}").props("fit=cover").classes(
                        "aspect-square rounded-lg bg-zinc-200" + (" ring-4 ring-zinc-900" if selected else ""))
                    if selected:
                        ui.badge("已选用", color="positive").classes("absolute top-2 left-2")

    def open_viewer(images: list, index: int) -> None:
        viewer_slot.clear()
        with viewer_slot:
            image_viewer(scene_id, images, index, gallery.refresh)

    gallery()
    viewer_slot = ui.element("div")
    ui.timer(5, lambda: candidate_count(scene_id) != shown and gallery.refresh())
    return gallery.refresh


def scene_editor(scene) -> None:
    saved = {column: scene[column] for column in PROMPT_LABELS}
    fields = {}
    save_buttons = []
    image_columns = ("image_positive", "image_negative")

    def set_unsaved(unsaved: bool) -> None:
        if unsaved != save_buttons[0].enabled:
            for button in save_buttons:
                button.set_enabled(unsaved)
            ui.run_javascript(f"window.unsavedPrompts = {str(unsaved).lower()}")

    def on_edit() -> None:
        set_unsaved(any(fields[c].value != saved[c] for c in PROMPT_LABELS))

    def unlock_when_empty(count: int) -> None:
        if count == 0:
            lock_notice.set_visibility(False)
            for column in image_columns:
                fields[column].props(remove="readonly")

    def copy_scene() -> None:
        execute("UPDATE scenes SET position = position + 1 WHERE episode_id = ? AND position > ?",
                scene["episode_id"], scene["position"])
        scene_id = execute("INSERT INTO scenes (episode_id, name, position, image_positive, image_negative, video_prompt) "
                           "SELECT episode_id, name || ' 副本', position + 1, image_positive, image_negative, video_prompt "
                           "FROM scenes WHERE id = ?", scene["id"])
        ui.navigate.to(f"/scene/{scene_id}")

    def delete_candidates() -> None:
        execute("DELETE FROM images WHERE scene_id = ?", scene["id"])
        refresh_gallery()

    def save() -> None:
        if any(fields[c].value != saved[c] for c in image_columns) and candidate_count(scene["id"]):
            ui.notify("已有候选图，图像提示词无法保存。可先复制文字，刷新后用“复制场景”新建场景再粘贴。", type="warning")
            return
        saved.update({c: fields[c].value for c in PROMPT_LABELS})
        execute("UPDATE scenes SET image_positive = ?, image_negative = ?, video_prompt = ? WHERE id = ?",
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
            if locked and column in image_columns:
                fields[column].props("readonly")

    ui.add_body_html("<script>window.addEventListener('beforeunload', "
                     "e => { if (window.unsavedPrompts) e.preventDefault() })</script>")

    with ui.tabs().props("dense no-caps inline-label align=justify active-bg-color=white indicator-color=transparent"
                         ).classes("segmented w-full mt-3") as tabs:
        image_tab = ui.tab("图像", icon="image")
        video_tab = ui.tab("视频", icon="movie")
    with ui.tab_panels(tabs, value=image_tab).props("transition-prev=fade transition-next=fade transition-duration=150"
                                                   ).classes("scene-panels w-full bg-transparent"):
        with ui.tab_panel(image_tab).classes("p-0 gap-1"):
            locked = candidate_count(scene["id"]) > 0
            with ui.column().classes("w-full gap-1 mt-3 px-3 pt-2 pb-1 rounded-lg bg-amber-50 text-amber-900 text-xs"
                                     ) as lock_notice:
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.icon("lock", size="16px")
                    ui.label("已有候选图，图像提示词不可编辑。如需修改，请删除全部候选图，或复制场景。")
                with ui.row().classes("w-full justify-end gap-1"):
                    ui.button("删除全部候选图", icon="delete_sweep", on_click=lambda: confirm_delete(
                        "全部候选图", delete_candidates)).props("flat dense no-caps color=amber-10")
                    ui.button("复制场景", icon="content_copy", on_click=copy_scene
                              ).props("flat dense no-caps color=amber-10")
            lock_notice.set_visibility(locked)
            prompt_fields(*image_columns)
            refresh_gallery = candidate_gallery(scene["id"], unlock_when_empty)
        with ui.tab_panel(video_tab).classes("p-0 gap-1"):
            prompt_fields("video_prompt")


@ui.page("/scene/{scene_id}")
def scene_page(scene_id: int):
    scene = visible_scene(scene_id, current_owner(), "s.*")
    if not scene:
        return RedirectResponse("/")
    episode_url = f"/episode/{scene['episode_id']}"
    page_frame(*episode_crumbs(scene["episode_id"]))

    def delete():
        execute("DELETE FROM scenes WHERE id = ?", scene_id)
        ui.navigate.to(episode_url)

    with ui.column().classes(CONTAINER + " gap-1"):
        ui.button("返回场景列表", icon="arrow_back", on_click=lambda: ui.navigate.to(episode_url)
                  ).props("flat dense color=grey-8 no-caps").classes("-ml-2")
        title_row(scene["name"], lambda name: execute("UPDATE scenes SET name = ? WHERE id = ?", name, scene_id))
        scene_editor(scene)
        ui.button("删除场景", icon="delete_outline", on_click=lambda: confirm_delete(scene["name"], delete)
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
