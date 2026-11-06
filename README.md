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
   - **加载角色提示词**: pick a character, outputs `positive`, `negative`, `character_id`. Use with 保存角色图 set to `full body, front view`.
   - **加载角色参考图**: pick a character and a view, outputs the selected front image, `positive`, `negative`, `view_prompt`, `character_id`, `view`.
   - **加载角色上传参考图**: pick a character, outputs the images uploaded on the character page as a list (images may differ in size), and `character_id`.
   - **保存角色图**: connect `images`, `character_id`, and `view` (pick it or connect it from 加载角色参考图).

To generate from the app, set `COMFYUI_URL` and `CHARACTER_FRONT_WORKFLOW` in `.env` (see `.env.example`). The workflow is a ComfyUI "Export (API)" file that uses 加载角色提示词 and ends with 保存角色图; the app fills in the character and randomizes every `seed` / `noise_seed` input on each run.

The scene list in the dropdown refreshes when ComfyUI reloads node definitions (press `R` or reload the page).
