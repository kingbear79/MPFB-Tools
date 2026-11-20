"""Verify the character library restores Rigify panels immediately after Append."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import bpy
from rigify import rig_ui_template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mpfb_tools import saved_assets


rig_id = "mpfb_character_ui_test"
armature = bpy.data.armatures.new("Library test rig")
rig = bpy.data.objects.new("Library test rig", armature)
bpy.context.collection.objects.link(rig)
armature["rig_id"] = rig_id
armature.collections.new("Torso")["rigify_ui_row"] = 1
body = bpy.data.objects.new("Library test body", bpy.data.meshes.new("Library test body"))
bpy.context.collection.objects.link(body)
body.parent = rig
body["MPFB_GEN_object_type"] = "Basemesh"

text = bpy.data.texts.new("Library test rig_ui.py")
text.write("\n".join(rig_ui_template.UI_IMPORTS))
text.write(rig_ui_template.UI_BASE_UTILITIES % rig_id)
text.write(rig_ui_template.UI_SLIDERS)
text.write(rig_ui_template.UI_LAYERS_PANEL)
text.write("\ndef register():\n    bpy.utils.register_class(RigUI)\n    bpy.utils.register_class(RigLayers)\nregister()\n")
text.use_module = True
rig["rig_ui"] = text

panel_id = "VIEW3D_PT_rig_layers_" + rig_id
assert bpy.types.Panel.bl_rna_get_subclass_py(panel_id) is None
with TemporaryDirectory() as folder:
    path = Path(folder) / "character.blend"
    metadata = saved_assets.save_character(bpy.context, body, path)
    metadata["name"] = "Library test character"
    bpy.data.objects.remove(body, do_unlink=True)
    bpy.data.objects.remove(rig, do_unlink=True)
    bpy.data.texts.remove(text)

    appended = saved_assets.append_character(bpy.context, path, metadata)
    rig = appended.parent
    layers = bpy.types.Panel.bl_rna_get_subclass_py(panel_id)
    main = bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_rig_ui_" + rig_id)
    assert layers is not None and main is not None
    assert rig["rig_ui"].use_module and bpy.context.active_object == rig
    assert layers.poll(bpy.context)
    bpy.ops.object.mode_set(mode="POSE")
    assert main.poll(bpy.context)
    bpy.ops.object.mode_set(mode="OBJECT")

    duplicate = saved_assets.append_character(bpy.context, path, metadata)
    assert duplicate != appended and duplicate.parent != rig
    assert duplicate.parent["rig_ui"] != rig["rig_ui"]
    assert bpy.types.Panel.bl_rna_get_subclass_py(panel_id) is layers
    saved_assets.activate_rigify_ui(bpy.context.scene.objects)
    assert bpy.types.Panel.bl_rna_get_subclass_py(panel_id) is layers
print("PASS character Append restores Rigify panels, including repeated imports", flush=True)
