# Prompt Manager

Run: `uv run prompt-manager`, then open `http://<host>:8080`.

## ComfyUI nodes

1. Link the node folder into ComfyUI:
   `ln -s "$(pwd)/comfyui_prompt_manager" /path/to/ComfyUI/custom_nodes/`
2. If the manager is not at `http://localhost:8080`, start ComfyUI with
   `PROMPT_MANAGER_URL=http://<host>:8080`.
3. Nodes (category `prompt_manager`):
   - **加载场景提示词**: pick a scene, outputs `positive`, `negative`, `scene_id`.
   - **保存候选图**: connect `images` and `scene_id`; images appear on the scene page.

The scene list in the dropdown refreshes when ComfyUI reloads node definitions (press `R` or reload the page).
