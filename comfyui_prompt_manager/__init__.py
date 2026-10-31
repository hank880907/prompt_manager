import io
import json
import os
import re
import urllib.request

import numpy as np
from PIL import Image

SERVER = os.environ.get("PROMPT_MANAGER_URL", "http://localhost:8080")


def request(path: str, png: bytes | None = None):
    headers = {"Content-Type": "image/png"} if png else {}
    with urllib.request.urlopen(urllib.request.Request(SERVER + path, data=png, headers=headers), timeout=30) as r:
        return json.loads(r.read())


def parse_scene_id(label: str) -> int | None:
    match = re.search(r"#(\d+)$", label)
    return int(match.group(1)) if match else None


class LoadScenePrompt:
    CATEGORY = "prompt_manager"
    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("positive", "negative", "scene_id")
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
        return prompts["image_positive"], prompts["image_negative"], scene_id


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
