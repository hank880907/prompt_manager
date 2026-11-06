import json
import random
import urllib.error
import urllib.request

from prompt_manager.config import COMFYUI_URL

# Matches VIEWS in comfyui_prompt_manager: the view dropdown values of the character nodes.
VIEW_PROMPTS = {
    "front": "full body, front view",
    "three_quarter": "three-quarter view, full body",
    "side": "side profile, full body",
    "back": "back view, full body",
    "face": "front face close-up",
    "face_three_quarter": "three-quarter face close-up",
    "seated": "seated, medium shot",
}


def call(path: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(COMFYUI_URL + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


def submit(workflow_path: str, inputs: dict[str, dict]) -> str:
    """inputs maps a node class_type to the inputs to set on every node of that type. Seeds are randomized
    so ComfyUI doesn't reuse its cached result."""
    with open(workflow_path) as file:
        workflow = json.load(file)
    for node in workflow.values():
        node["inputs"].update(inputs.get(node.get("class_type"), {}))
        for key in ("seed", "noise_seed"):
            if isinstance(node["inputs"].get(key), int):
                node["inputs"][key] = random.randrange(2**32)
    try:
        return call("/prompt", {"prompt": workflow})["prompt_id"]
    except urllib.error.HTTPError as error:
        message = json.loads(error.read()).get("error", {})
        raise RuntimeError(f"{message.get('message', error)} {message.get('details', '')}") from error


def queued_ids() -> set[str] | None:
    """Prompt ids that are running or waiting, or None if ComfyUI can't be reached."""
    try:
        queue = call("/queue")
    except OSError:
        return None
    return {item[1] for item in queue["queue_running"] + queue["queue_pending"]}
