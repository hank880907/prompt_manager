# Prompt Manager

1. Copy `.env.example` to `.env` and set `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
2. Run: `uv run prompt-manager`, then open `http://<host>:8080`.
3. Log in as admin and add users from the user management page (person icon, top right).

All app data (`prompts.db`, `images/`, `thumbnails/`, `previews/`, `secret.key`, `.nicegui/`) lives in `DATA_DIR`, `data/` in the repo by default. `.env` is always read from the current folder.

Put HTTPS in front of it (e.g. Caddy) before exposing it publicly; otherwise passwords are sent in plain text.

## ComfyUI nodes

1. Link the node folder into ComfyUI:
   `ln -s "$(pwd)/comfyui_prompt_manager" /path/to/ComfyUI/custom_nodes/`
2. Start ComfyUI with the manager's address, e.g. `PROMPT_MANAGER_URL=https://<host>`.
   If ComfyUI's IP is not in `TRUSTED_IPS` (see `.env.example`), also set
   `PROMPT_MANAGER_USER=<name> PROMPT_MANAGER_PASSWORD=<password>`.
3. Nodes (category `prompt_manager`):
   - **加载场景提示词**: pick a scene, outputs `positive`, `negative`, `scene_id`, `aspect_ratio` (connects to the Resolution Selector node).
   - **保存候选图**: connect `images` and `scene_id`; images appear on the scene page.

The scene list in the dropdown refreshes when ComfyUI reloads node definitions (press `R` or reload the page).
