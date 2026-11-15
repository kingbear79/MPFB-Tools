"""Generate and cache library icons without blocking the sidebar."""

import os
import json
from pathlib import Path
import subprocess
import tempfile

import bpy
import bpy.utils.previews

from .library import BODY, BODY_OBJECT, SHOE_OBJECT
from . import catalog, library_backup


icons = None
pending = {}
failed = set()
jobs = {}


def source_stamp(source):
    stat = source.stat()
    return stat.st_mtime_ns, stat.st_size


def icon_for(path, category):
    key = str(path)
    source = path / "Vorlage.blend"
    preview = path / "Vorschau-v2.png"
    try:
        stamp = source_stamp(source)
        if preview.is_file() and preview.stat().st_mtime_ns >= stamp[0]:
            cache_key = f"{key}:{preview.stat().st_mtime_ns}"
            if cache_key not in icons:
                for entry in list(icons.keys()):
                    if entry.startswith(key + ":"):
                        del icons[entry]
                icons.load(cache_key, str(preview), "IMAGE")
            return icons[cache_key].icon_id
    except (OSError, RuntimeError):
        return 0

    if key not in jobs and (key, stamp) not in failed:
        pending[key] = (path, category, stamp)
        if not bpy.app.timers.is_registered(work):
            bpy.app.timers.register(work, first_interval=.1)
    return 0


def work():
    for key, (process, output, path, stamp) in list(jobs.items()):
        status = process.poll()
        if status is None:
            continue
        del jobs[key]
        try:
            if status == 0 and output.is_file():
                if source_stamp(path / "Vorlage.blend") == stamp:
                    os.replace(output, path / "Vorschau-v2.png")
                    library_backup.mark_dirty(path.parents[2])
            else:
                failed.add((key, stamp))
        except OSError:
            failed.add((key, stamp))
        finally:
            output.unlink(missing_ok=True)
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    if pending and not jobs:
        key, (path, category, stamp) = pending.popitem()
        output = None
        try:
            # Stage in the same library, outside the replaceable asset folder.
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".png", delete=False) as stream:
                output = Path(stream.name)
            script = Path(__file__).with_name("preview_render.py")
            mode = "object"
            if category in catalog.GROOMS or category == catalog.CHARACTERS:
                metadata = json.loads((path / "asset.json").read_text(encoding="utf-8"))
                mode = "collection" if category == catalog.CHARACTERS else "groom"
                name = metadata["collection" if mode == "collection" else "object"]
            else:
                name = BODY_OBJECT if category == BODY else SHOE_OBJECT
            process = subprocess.Popen(
                [bpy.app.binary_path, "-b", "-Y", "--factory-startup", "--python-exit-code", "1",
                 "-P", str(script), "--", str(path / "Vorlage.blend"), name, str(output), mode],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            jobs[key] = (process, output, path, stamp)
        except (OSError, ValueError, KeyError):
            failed.add((key, stamp))
            if output:
                output.unlink(missing_ok=True)
    return .25 if jobs or pending else None


def register():
    global icons
    icons = bpy.utils.previews.new()


def unregister():
    global icons
    if bpy.app.timers.is_registered(work):
        bpy.app.timers.unregister(work)
    for process, output, _, _ in jobs.values():
        if process.poll() is None:
            process.terminate()
        output.unlink(missing_ok=True)
    jobs.clear()
    pending.clear()
    failed.clear()
    bpy.utils.previews.remove(icons)
    icons = None
