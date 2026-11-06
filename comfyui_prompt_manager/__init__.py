import base64
import io
import json
import os
import re
import urllib.request

import numpy as np
from PIL import Image

SERVER = os.environ.get("PROMPT_MANAGER_URL", "http://localhost:8080")
CREDENTIALS = f"{os.environ.get('PROMPT_MANAGER_USER', '')}:{os.environ.get('PROMPT_MANAGER_PASSWORD', '')}"
AUTH_HEADER = "Basic " + base64.b64encode(CREDENTIALS.encode()).decode()


def request(path: str, png: bytes | None = None):
    headers = {"Authorization": AUTH_HEADER}
    if png:
        headers["Content-Type"] = "image/png"
    with urllib.request.urlopen(urllib.request.Request(SERVER + path, data=png, headers=headers), timeout=30) as r:
        return json.loads(r.read())


# Labels match ComfyUI's Resolution Selector so the output can connect to its aspect_ratio input.
ASPECT_RATIO_LABELS = {
    "1:1": "1:1 (Square)",
    "2:3": "2:3 (Portrait Photo)",
    "3:2": "3:2 (Photo)",
    "3:4": "3:4 (Portrait Standard)",
    "4:3": "4:3 (Standard)",
    "9:16": "9:16 (Portrait Widescreen)",
    "16:9": "16:9 (Widescreen)",
    "21:9": "21:9 (Ultrawide)",
}


def parse_scene_id(label: str) -> int | None:
    match = re.search(r"#(\d+)$", label)
    return int(match.group(1)) if match else None


class LoadScenePrompt:
    CATEGORY = "prompt_manager"
    RETURN_TYPES = ("STRING", "STRING", "INT", list(ASPECT_RATIO_LABELS.values()))
    RETURN_NAMES = ("positive", "negative", "scene_id", "aspect_ratio")
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        try:
            labels = [s["label"] for s in request("/api/scenes")]
        except OSError:
            labels = []
        return {"required": {"scene": (labels or [f"无法连接 {SERVER} 或没有场景"],)}}

    @classmethod
    def VALIDATE_INPUTS(cls, scene):
        return True if parse_scene_id(scene) else "请选择场景"

    @classmethod
    def IS_CHANGED(cls, scene):
        return json.dumps(request(f"/api/scenes/{parse_scene_id(scene)}"))

    def load(self, scene):
        scene_id = parse_scene_id(scene)
        prompts = request(f"/api/scenes/{scene_id}")
        return prompts["image_positive"], prompts["image_negative"], scene_id, ASPECT_RATIO_LABELS[prompts["aspect_ratio"]]


class SaveSceneImage:
    CATEGORY = "prompt_manager"
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "scene_id": ("INT", {"forceInput": True})}}

    def save(self, images, scene_id):
        for image in images:
            pixels = np.clip(image.cpu().numpy() * 255, 0, 255).astype(np.uint8)
            buffer = io.BytesIO()
            Image.fromarray(pixels).save(buffer, "PNG")
            request(f"/api/scenes/{scene_id}/images", buffer.getvalue())
        return ()


NODE_CLASS_MAPPINGS = {
    "PromptManagerLoadScene": LoadScenePrompt,
    "PromptManagerSaveImage": SaveSceneImage,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptManagerLoadScene": "加载场景提示词",
    "PromptManagerSaveImage": "保存候选图",
}
