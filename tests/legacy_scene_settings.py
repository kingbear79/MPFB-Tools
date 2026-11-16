"""Run with Blender 4.5: blender -b --factory-startup --python-exit-code 1 -P tests/legacy_scene_settings.py."""
import importlib
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
addon = importlib.import_module("mpfb_tools")
scene = bpy.context.scene


class LegacyGeneratorSettings(bpy.types.PropertyGroup):
    selected_id: bpy.props.StringProperty()
    asset_name: bpy.props.StringProperty()
    filepath: bpy.props.StringProperty()


bpy.utils.register_class(LegacyGeneratorSettings)
for category in ("body", "shoes"):
    setattr(bpy.types.Scene, f"mpfb_tools_{category}", bpy.props.PointerProperty(type=LegacyGeneratorSettings))
for key in addon.library_ui.LEGACY_GROOM_SELECTIONS.values():
    setattr(bpy.types.Scene, key, bpy.props.StringProperty())

scene.mpfb_tools_hairstyle = "classic_side_part"
scene.mpfb_tools_beard = "B04"
scene.mpfb_tools_eyebrow = "A02"
scene.mpfb_tools_shoes.selected_id = "existing-shoes"
scene.mpfb_tools_body.asset_name = "Existing template"
scene.mpfb_tools_body.filepath = "//templates/body.blend"

addon.register()
# Reproduce the Legacy add-on being disabled after the extension was enabled.
for key in ("mpfb_tools_body", "mpfb_tools_shoes", *addon.library_ui.LEGACY_GROOM_SELECTIONS.values()):
    delattr(bpy.types.Scene, key)
bpy.utils.unregister_class(LegacyGeneratorSettings)
# A panel opening before the migration must be allowed to read the defaults.
assert addon.generator_settings(scene, "shoes").selected_id == ""
addon.migrate_scene_settings()

assert addon.selected_groom(scene) == "H01"
assert addon.selected_groom(scene, beard=True) == "B04"
assert addon.selected_groom(scene, eyebrow=True) == "A02"
assert addon.generator_settings(scene, "shoes").selected_id == "existing-shoes"
body = addon.generator_settings(scene, "body")
assert body.asset_name == "Existing template"
assert body.filepath == "//templates/body.blend"

addon.library_ui.choose(scene, "H", "")
addon.generator_settings(scene, "shoes").selected_id = "new-shoes"
addon.migrate_scene_settings()
assert addon.selected_groom(scene) == ""
assert addon.generator_settings(scene, "shoes").selected_id == "new-shoes"
addon.unregister()
print("PASS legacy scene settings", flush=True)
