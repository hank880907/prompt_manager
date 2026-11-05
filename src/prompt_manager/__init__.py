from contextlib import suppress

from prompt_manager.config import ADMIN_PASSWORD, ADMIN_USERNAME


def main() -> None:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        print("请在 .env 中设置 ADMIN_USERNAME 和 ADMIN_PASSWORD")
        return
    from nicegui import ui

    from prompt_manager import api, pages  # noqa: F401  registers routes
    from prompt_manager.auth import storage_secret
    from prompt_manager.images import remove_orphans

    remove_orphans()
    with suppress(KeyboardInterrupt):
        ui.run(title="提示词管理器", language="zh-CN", host="0.0.0.0", port=8080, reload=False,
               storage_secret=storage_secret())
