"""Blender regression checks for independent, persistent and animated facial controls."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mpfb_tools as addon
from mpfb_tools import mimic, saved_assets

addon.register()
assert len(mimic.UNITS) == len(set(mimic.UNITS)) == 52
# A miniature basemesh lets the standalone tests run without MPFB asset packs.
mimic.BASE_VERTEX_COUNT = 3


def figure(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    body = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(body)
    body["MPFB_GEN_object_type"] = "Basemesh"
    body.shape_key_add(name="Basis")
    model = body.shape_key_add(name="head-scale-horiz-incr")
    model.data[0].co.x += .1
    model.value = .7
    viseme = body.shape_key_add(name="viseme_aa")
    viseme.value = .3
    for name in mimic.UNITS:
        key = body.shape_key_add(name="!ex-" + name)
        key.data[0].co.z += .1
    body["mpfb_tools_mimic_prepared"] = True
    return body


body = figure("First figure")
other = figure("Second figure")
saved_assets.select_only(bpy.context, body)
body.mpfb_tools_mimic.smile = .8
assert abs(mimic.unit_key(body, "mouthSmileLeft").value - .8) < 1e-5
assert abs(mimic.unit_key(body, "mouthSmileRight").value - .8) < 1e-5
assert other.mpfb_tools_mimic.smile == 0
saved_assets.select_only(bpy.context, other)
other.mpfb_tools_mimic.smile = .2
assert abs(body.mpfb_tools_mimic.smile - .8) < 1e-5
assert mimic.selected_body(bpy.context) == other

saved_assets.select_only(bpy.context, body)
body.mpfb_tools_mimic.strength = .5
body.mpfb_tools_mimic.preset = "HAPPY"
assert bpy.ops.mpfb_tools.apply_mimic() == {"FINISHED"}
assert abs(body.mpfb_tools_mimic.smile - .35) < 1e-5
assert bpy.ops.mpfb_tools.apply_mimic(neutral=True) == {"FINISHED"}
assert all(value == 0 for value in mimic.read_expression(body).values())
assert body.data.shape_keys.key_blocks["head-scale-horiz-incr"].value > .69
assert body.data.shape_keys.key_blocks["viseme_aa"].value > .29

# Transfer neutral offsets into the child's object space without changing its Basis.
mesh = bpy.data.meshes.new("Attached topology")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
child = bpy.data.objects.new("Attached topology", mesh)
bpy.context.collection.objects.link(child)
child.parent = body
child.scale = (2, 2, 2)
bpy.context.view_layer.update()
mapping = {i: {"verts": (i, i, i), "weights": (1, 0, 0)} for i in range(3)}
assert mimic.transfer_keys(body, child, mapping, []) == 52
target = child.data.shape_keys.key_blocks["MPFB-Tools · jawOpen"]
assert abs(target.data[0].co.z - .05) < 1e-6
assert child.data.shape_keys.reference_key.data[0].co == Vector((0, 0, 0))
body.mpfb_tools_mimic.jaw = .6
bpy.context.view_layer.update()
assert abs(target.value - .6) < 1e-5
assert mimic.transfer_keys(body, child, mapping, []) == 0

duplicate = bpy.data.objects.new("Linked duplicate", body.data)
bpy.context.collection.objects.link(duplicate)
assert mimic.shared_mesh(body)
bpy.data.objects.remove(duplicate, do_unlink=True)
assert not mimic.shared_mesh(body)
body.data.use_fake_user = True
assert not mimic.shared_mesh(body)

with TemporaryDirectory() as temporary:
    root = Path(temporary)
    mimic.expression_folder = lambda _context: root / "Bibliothek" / "expressions"
    body.mpfb_tools_mimic.smile = .42
    assert bpy.ops.mpfb_tools.save_mimic(name="Ein eigener Ausdruck") == {"FINISHED"}
    path = next(mimic.expression_folder(None).glob("*.json"))
    data = json.loads(path.read_text())
    assert data["name"] == "Ein eigener Ausdruck"
    assert abs(data["face_units"]["mouthSmileLeft"] - .42) < 1e-5
    assert any(item[0] == path.stem for item in mimic.preset_items(body.mpfb_tools_mimic, bpy.context))
    body.mpfb_tools_mimic.preset = path.stem
    body.mpfb_tools_mimic.strength = 1
    mimic.apply_expression(body, {})
    assert bpy.ops.mpfb_tools.apply_mimic() == {"FINISHED"}
    assert abs(body.mpfb_tools_mimic.smile - .42) < 1e-5

    for value in (float("nan"), float("inf"), -1, 2):
        try:
            mimic.validate_expression({"face_units": {"jawOpen": value}})
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid expression accepted")

    # Existing character-library save/load must preserve facial values and remap drivers.
    output = root / "figure.blend"
    metadata = saved_assets.save_character(bpy.context, body, output)
    metadata["name"] = "Mimik round-trip"
    appended = saved_assets.append_character(bpy.context, output, metadata)
    assert appended != body and appended.data != body.data
    assert abs(appended.mpfb_tools_mimic.smile - .42) < 1e-5
    appended.mpfb_tools_mimic.jaw = .15
    bpy.context.view_layer.update()
    attached = next(obj for obj in appended.children if obj.type == "MESH")
    assert abs(attached.data.shape_keys.key_blocks["MPFB-Tools · jawOpen"].value - .15) < 1e-5
    assert abs(target.value - .6) < 1e-5

# Playback uses native shape-key animation and drivers, without refitting the rig.
saved_assets.select_only(bpy.context, body)
bpy.context.scene.frame_set(1)
body.mpfb_tools_mimic.jaw = 0
assert bpy.ops.mpfb_tools.keyframe_mimic() == {"FINISHED"}
bpy.context.scene.frame_set(11)
body.mpfb_tools_mimic.jaw = 1
assert bpy.ops.mpfb_tools.keyframe_mimic() == {"FINISHED"}
bpy.context.scene.frame_set(6)
bpy.context.view_layer.update()
assert abs(body.mpfb_tools_mimic.jaw - .5) < 1e-5
assert abs(target.value - .5) < 1e-5

# Helper-derived clothes inherit Basemesh tags, but are neither a source nor a target.
rig = bpy.data.objects.new("Figure rig", bpy.data.armatures.new("Figure rig"))
bpy.context.collection.objects.link(rig)
body.parent = rig
clothing_mesh = bpy.data.meshes.new("Helper clothing")
clothing_mesh.from_pydata([(0, 0, 0)], [], [])
clothing = bpy.data.objects.new("Kleidung.002", clothing_mesh)
bpy.context.collection.objects.link(clothing)
clothing.parent = rig
clothing["MPFB_GEN_object_type"] = "Basemesh"
clothing["MPFB_HUM_is_human_project"] = True
child.parent = rig
child["MPFB_GEN_object_type"] = "Proxymeshes"
body.hide_set(True)
assert mimic.source_body(bpy.context.scene, child) == body
assert mimic.source_body(bpy.context.scene, rig) == body
assert mimic.source_body(bpy.context.scene, clothing) == body
assert mimic.facial_targets(bpy.context.scene, body) == [child]
assert not mimic.is_source_body(clothing)
body.hide_viewport = True
bpy.context.scene.frame_set(1)
bpy.context.view_layer.update()
assert abs(target.value) < 1e-5
bpy.context.scene.frame_set(11)
bpy.context.view_layer.update()
assert abs(target.value - 1) < 1e-5
body.hide_viewport = False
bpy.context.scene.frame_set(6)

# Genuine clothes with valid metadata are excluded as well, even around the head.
clothing["MPFB_GEN_object_type"] = "Clothes"
assert mimic.facial_targets(bpy.context.scene, body) == [child]
body.hide_set(False)

# Preparation must never request an MHCLO file for helper-derived clothes.
clothing["MPFB_GEN_object_type"] = "Basemesh"
clothing.shape_key_add(name="Basis")
clothing.shape_key_add(name="head-scale-horiz-incr").value = .4
requested = []


def find_mapping(obj):
    assert obj == child, "Non-facial clothing was included in MHCLO discovery"
    requested.append(obj)
    return "topology.proxy"


class Mapping:
    def load(self, path):
        assert path == "topology.proxy"
        self.verts = mapping


services = SimpleNamespace(ClothesService=SimpleNamespace(find_clothes_absolute_path=find_mapping),
                           TargetService=SimpleNamespace())
with TemporaryDirectory() as temporary:
    reference = Path(temporary) / "basemesh.json"
    reference.write_text(json.dumps({"topology": mimic.topology(body.data)}))
    with patch.object(mimic, "TEMPLATE", reference), patch.dict(sys.modules, {
        "bl_ext.blender_org.mpfb.services": services,
        "bl_ext.blender_org.mpfb.entities.clothes.mhclo": SimpleNamespace(Mhclo=Mapping),
    }):
        assert mimic.prepare(bpy.context, body) == 1
        assert requested == [child]
        assert len(clothing.data.shape_keys.key_blocks) == 2
        assert clothing.data.shape_keys.key_blocks["head-scale-horiz-incr"].value > .39
        assert clothing.data.shape_keys.animation_data is None
        requested.clear()
        reference.write_text(json.dumps({"topology": "modified topology"}))
        try:
            mimic.prepare(bpy.context, body)
        except ValueError as error:
            assert "Topologie" in str(error)
        else:
            raise AssertionError("Modified source topology was accepted")
        assert requested == []

addon.unregister()
assert not hasattr(bpy.types.Object, "mpfb_tools_mimic")
addon.register()
assert abs(body.mpfb_tools_mimic.jaw - .5) < 1e-5
addon.unregister()
print("PASS mimic: per-figure controls, presets, neutral, transfer, library round-trip and animation", flush=True)
