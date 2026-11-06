import base64
import io
import json
import os
import re
import urllib.request

import numpy as np
import torch
from PIL import Image

SERVER = os.environ.get("PROMPT_MANAGER_URL", "http://localhost:8080")
CREDENTIALS = f"{os.environ.get('PROMPT_MANAGER_USER', '')}:{os.environ.get('PROMPT_MANAGER_PASSWORD', '')}"
AUTH_HEADER = "Basic " + base64.b64encode(CREDENTIALS.encode()).decode()


def fetch(path: str, png: bytes | None = None) -> bytes:
    headers = {"Authorization": AUTH_HEADER}
    if png:
        headers["Content-Type"] = "image/png"
    with urllib.request.urlopen(urllib.request.Request(SERVER + path, data=png, headers=headers), timeout=30) as r:
        return r.read()


def request(path: str, png: bytes | None = None):
    return json.loads(fetch(path, png))


def upload(path: str, images) -> None:
    for image in images:
        pixels = np.clip(image.cpu().numpy() * 255, 0, 255).astype(np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(pixels).save(buffer, "PNG")
        request(path, buffer.getvalue())


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


# Keys match VIEWS on the server; the prompt text doubles as the dropdown label.
VIEWS = {
    "front": "full body, front view",
    "three_quarter": "three-quarter view, full body",
    "side": "side profile, full body",
    "back": "back view, full body",
    "face": "front face close-up",
    "face_three_quarter": "three-quarter face close-up",
    "seated": "seated, medium shot",
}
VIEW_KEYS = {prompt: key for key, prompt in VIEWS.items()}


def parse_id(label: str) -> int | None:
    match = re.search(r"#(\d+)$", label)
    return int(match.group(1)) if match else None


def labels(path: str, kind: str) -> list[str]:
    try:
        return [item["label"] for item in request(path)] or [f"没有{kind}"]
    except OSError:
        return [f"无法连接 {SERVER}"]


class LoadScenePrompt:
    CATEGORY = "prompt_manager"
    RETURN_TYPES = ("STRING", "STRING", "INT", list(ASPECT_RATIO_LABELS.values()))
    RETURN_NAMES = ("positive", "negative", "scene_id", "aspect_ratio")
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": (labels("/api/scenes", "场景"),)}}

    @classmethod
    def VALIDATE_INPUTS(cls, scene):
        return True if parse_id(scene) else "请选择场景"

    @classmethod
    def IS_CHANGED(cls, scene):
        return json.dumps(request(f"/api/scenes/{parse_id(scene)}"))

    def load(self, scene):
        scene_id = parse_id(scene)
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
        upload(f"/api/scenes/{scene_id}/images", images)
        return ()


class LoadCharacterPrompt:
    CATEGORY = "prompt_manager"
    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("positive", "negative", "character_id")
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"character": (labels("/api/characters", "角色"),)}}

    @classmethod
    def VALIDATE_INPUTS(cls, character, **_):
        return True if parse_id(character) else "请选择角色"

    @classmethod
    def IS_CHANGED(cls, character, **_):
        return json.dumps(request(f"/api/characters/{parse_id(character)}"))

    def load(self, character):
        character_id = parse_id(character)
        prompts = request(f"/api/characters/{character_id}")
        return prompts["positive"], prompts["negative"], character_id


class LoadCharacterReference(LoadCharacterPrompt):
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT", list(VIEWS.values()))
    RETURN_NAMES = ("image", "positive", "negative", "view_prompt", "character_id", "view")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"character": (labels("/api/characters", "角色"),), "view": (list(VIEWS.values())[1:],)}}

    def load(self, character, view):
        positive, negative, character_id = super().load(character)
        with Image.open(io.BytesIO(fetch(f"/api/characters/{character_id}/reference"))) as image:
            pixels = np.array(image.convert("RGB")).astype(np.float32) / 255
        return torch.from_numpy(pixels)[None], positive, negative, view, character_id, view


class SaveCharacterImage:
    CATEGORY = "prompt_manager"
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "character_id": ("INT", {"forceInput": True}),
                             "view": (list(VIEWS.values()),)}}

    def save(self, images, character_id, view):
        upload(f"/api/characters/{character_id}/images?view={VIEW_KEYS[view]}", images)
        return ()


NODE_CLASS_MAPPINGS = {
    "PromptManagerLoadScene": LoadScenePrompt,
    "PromptManagerSaveImage": SaveSceneImage,
    "PromptManagerLoadCharacter": LoadCharacterPrompt,
    "PromptManagerLoadCharacterReference": LoadCharacterReference,
    "PromptManagerSaveCharacterImage": SaveCharacterImage,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptManagerLoadScene": "加载场景提示词",
    "PromptManagerSaveImage": "保存候选图",
    "PromptManagerLoadCharacter": "加载角色提示词",
    "PromptManagerLoadCharacterReference": "加载角色参考图",
    "PromptManagerSaveCharacterImage": "保存角色图",
}
