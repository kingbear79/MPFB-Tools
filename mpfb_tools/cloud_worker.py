"""Prepare reference images and call OpenAI in an isolated Blender process."""
import base64
import json
import os
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud_api import analyze


def image_data_uri(path, main, workspace):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        if min(width, height) < 1:
            raise ValueError(f"„{path.name}“ konnte nicht als Bild gelesen werden.")
        factor = min(1.0, (960 if main else 640) / max(width, height))
        if factor < 1:
            image.scale(max(1, round(width * factor)), max(1, round(height * factor)))
        settings = bpy.context.scene.render.image_settings
        settings.file_format = "JPEG"
        settings.color_mode = "RGB"
        settings.quality = 86
        bpy.context.scene.view_settings.view_transform = "Standard"
        output = workspace / "prepared.jpg"
        try:
            image.save_render(str(output))
            encoded = base64.b64encode(output.read_bytes()).decode("ascii")
            return "data:image/jpeg;base64," + encoded, width / height
        finally:
            output.unlink(missing_ok=True)
    finally:
        bpy.data.images.remove(image)


def run(request, workspace, key, transport=None):
    options = {} if transport is None else {"transport": transport}
    recipes, requested, usage = analyze(
        request["paths"], request["kinds"], request["model"], Path(request["cache"]),
        key, request["online"], lambda path, main: image_data_uri(path, main, workspace),
        refresh=request.get("refresh", False), **options,
    )
    return {"recipes": recipes, "requested": requested, "usage": usage}


def main(request_path, result_path):
    source, destination = Path(request_path), Path(result_path)
    try:
        data = run(json.loads(source.read_text(encoding="utf-8")), source.parent,
                   os.environ.pop("MPFB_REFERENCE_KEY", ""))
    except (ValueError, RuntimeError, OSError) as error:
        data = {"error": str(error)}
    destination.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[sys.argv.index("--") + 1:])
