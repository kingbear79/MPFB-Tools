"""Standalone figure and groom libraries built from Blender datablocks."""
import json
from pathlib import Path
import subprocess

import bpy
from mathutils import Matrix

from . import hair_binding as binding
from .hair import add_hair_modifier, object_type
from .library import discard_new


CHARACTER_COLLECTION = "MPFB Library Character"
GROOM_OBJECT = "MPFB Library Groom"
STANDARD = Path(__file__).with_name("defaults") / "basis_baer.json"
OWNER = "mpfb_tools_figure"
GROOM_PREVIEW = "mpfb_tools_reference_preview"


def select_only(context, obj):
    for other in context.selected_objects:
        if other != obj:
            other.select_set(False)
    if obj is not None:
        obj.select_set(True)
    context.view_layer.objects.active = obj


def figure_base(context, selected):
    if selected is None:
        raise ValueError("Wähle eine MPFB-Figur aus.")
    if selected.type == "CURVES":
        surface = binding.mesh_surface(selected)
        selected = surface if surface is not None else selected
    obj = selected
    while obj is not None:
        base = binding.body_for(context.scene, obj) or obj.get(OWNER)
        if base and base.name in context.scene.objects:
            return base
        if obj.type == "ARMATURE":
            matches = [candidate for candidate in context.scene.objects
                       if candidate.type == "MESH" and object_type(candidate) == "basemesh"
                       and (candidate.parent == obj or any(
                           mod.type == "ARMATURE" and mod.object == obj for mod in candidate.modifiers))]
            if len(matches) == 1:
                return matches[0]
        obj = obj.parent
    raise ValueError("Wähle das Körpermesh oder Rig einer MPFB-Figur aus.")


def select_figure(context, selected, base=None):
    if selected is not None and selected.type in {"MESH", "ARMATURE"}:
        if selected.type == "ARMATURE" and object_type(selected) == "skeleton":
            select_only(context, selected)
            return
        if object_type(selected) in {"basemesh", *binding.PROXIES}:
            select_only(context, selected)
            return
    base = base if base is not None else figure_base(context, selected)
    rig = base.parent
    select_only(context, rig if rig and rig.type == "ARMATURE" else base)


def create_standard(context):
    from bl_ext.blender_org.mpfb.services import HumanService, MeshService, RigService, SystemService

    configuration = json.loads(STANDARD.read_text(encoding="utf-8"))
    preset = dict(configuration["preset"], name="Basis-Bär")
    options = configuration["settings"]
    rig_type = preset["rig"] if options["override_rig"] == "PRESET" else options["override_rig"]
    if rig_type.startswith("rigify.") and not SystemService.check_for_rigify():
        raise ValueError("Aktiviere Rigify in Blender, um den Basis-Bär zu laden.")
    old_selection = list(context.selected_objects)
    old_active = context.active_object
    existing = set(bpy.data.user_map())
    try:
        body = HumanService.deserialize_from_dict(preset, options)
        if body is None:
            raise RuntimeError("MPFB hat keine Standard-Figur erzeugt.")
        group = configuration["preselect_group"]
        rig = body.parent
        select_only(context, body)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            MeshService.select_all_vertices_in_vertex_group_for_active_object(group or None, deselect_other=True)
        finally:
            if context.mode == "EDIT_MESH":
                bpy.ops.object.mode_set(mode="OBJECT")
        for slot in body.material_slots:
            if slot.material is not None and slot.material.name.lower().endswith(group.lower()):
                body.active_material_index = slot.slot_index
                break
        if rig is not None and rig_type.startswith("rigify.") and configuration["auto_generate_rigify"]:
            generated = RigService.generate_rigify_rig(rig, meta_rig_action=configuration["meta_rig_action"])
            if generated is None:
                raise RuntimeError("Rigify konnte das Rig der Standard-Figur nicht erzeugen.")
        select_figure(context, body.parent or body, body)
        return body
    except Exception:
        discard_new(existing)
        for obj in old_selection:
            obj.select_set(True)
        context.view_layer.objects.active = old_active
        raise


def owned_objects(scene, body):
    result = {body}
    if body.parent is not None and body.parent.type == "ARMATURE":
        result.add(body.parent)
    result.update(mod.object for mod in body.modifiers if mod.type == "ARMATURE" and mod.object is not None)
    while True:
        added = {
            obj for obj in scene.objects if obj not in result and (
                obj.parent in result or obj.get(OWNER) == body
                or (obj.type == "CURVES" and obj.data.surface in result)
                or any(getattr(c, "target", None) in result for c in obj.constraints)
                or (obj.type == "MESH" and any(mod.type == "ARMATURE" and mod.object in result
                                                for mod in obj.modifiers))
                or (obj.type == "ARMATURE" and getattr(obj.data, "rigify_target_rig", None) in result)
            )
        }
        if not added:
            break
        result.update(added)
    return result


def write_blend(path, datablocks):
    bpy.data.libraries.write(str(path), set(datablocks), fake_user=True, compress=True, path_remap="ABSOLUTE")
    # Data blocks with external packed assets are safe to share across computers.
    # Pack external textures in an isolated process whenever this file has them.
    users = bpy.data.user_map()
    needed = set(datablocks)
    outgoing = {}
    for dependency, references in users.items():
        for user in references:
            outgoing.setdefault(user, []).append(dependency)
    pending = list(needed)
    while pending:
        for dependency in outgoing.get(pending.pop(), ()):
            if dependency not in needed:
                needed.add(dependency)
                pending.append(dependency)
    if any(isinstance(data, bpy.types.Image) and data.source in {"FILE", "TILED"}
           and data.filepath and not data.packed_files for data in needed):
        script = Path(__file__).with_name("pack_preview_source.py")
        try:
            run = subprocess.run([bpy.app.binary_path, "-b", "-Y", "--factory-startup", str(path),
                                  "-t", "4", "--python-exit-code", "1", "-P", str(script)],
                                 capture_output=True, text=True, timeout=180, check=False)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Das Packen der externen Texturen hat zu lange gedauert.") from error
        if run.returncode:
            raise RuntimeError("Externe Texturen konnten nicht in die Vorlage übernommen werden.")


def save_character(context, body, output):
    collection = bpy.data.collections.new(CHARACTER_COLLECTION)
    objects = owned_objects(context.scene, body)
    try:
        for obj in objects:
            collection.objects.link(obj)
        write_blend(output, {collection})
        return {"collection": collection.name, "base": body.name}
    finally:
        bpy.data.collections.remove(collection)


def append_character(context, path, meta):
    existing = set(bpy.data.user_map())
    try:
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            if meta["collection"] not in source.collections:
                raise ValueError("Die gespeicherte Figuren-Sammlung fehlt.")
            target.collections = [meta["collection"]]
        collection = target.collections[0]
        if collection is None:
            raise ValueError("Die gespeicherte Figur konnte nicht geladen werden.")
        bases = [obj for obj in collection.all_objects if obj.type == "MESH" and object_type(obj) == "basemesh"]
        if len(bases) != 1:
            raise ValueError("Die Vorlage muss genau eine MPFB-Figur enthalten.")
        context.collection.children.link(collection)
        collection.name = meta["name"]
        body = bases[0]
        context.view_layer.update()
        select_figure(context, body.parent or body, body)
        return body
    except Exception:
        discard_new(existing)
        raise


def binding_surface(base, obj):
    return binding.Surface(obj.data, base.matrix_world.inverted_safe() @ obj.matrix_world,
                           binding.skin_group(obj), obj)


def save_groom(context, obj, output):
    if obj.type != "CURVES" or not len(obj.data.curves):
        raise ValueError("Wähle ein Hair-Curves-Objekt mit Strähnen aus.")
    source = binding.mesh_surface(obj)
    if source is None:
        raise ValueError("Binde die Hair Curves an die MPFB-Figur, bevor du sie speicherst.")
    base = figure_base(context, obj)
    base_surface = binding_surface(base, base)
    surface = base_surface if source == base else binding_surface(base, source)
    uv = base.data.uv_layers.active
    if uv is None:
        raise ValueError("Das Basismesh braucht eine UV-Map.")
    frame = base.matrix_world.inverted_safe() @ obj.matrix_world
    result = binding.transfer(obj, surface, base_surface, base_surface, frame, uv.name, None)
    existing = set(bpy.data.user_map())
    try:
        copy = obj.copy()
        copy.data = obj.data.copy()
        copy.name = GROOM_OBJECT
        binding.apply_transfer(copy, base, uv.name, result)
        copy.data.surface = None
        copy.parent = None
        for prop in (OWNER, GROOM_PREVIEW, binding.BASE, binding.MESH, binding.MATRIX, binding.CURVE_MATRIX, binding.SKIN):
            if prop in copy:
                del copy[prop]
        # Store only the rest skin triangles, with the same triangle order
        # used by the stable per-strand anchors.
        reference = bpy.data.meshes.new("MPFB Hair Reference")
        reference.from_pydata(base_surface.raw, [], base_surface.faces)
        copy[binding.MESH] = reference
        copy.constraints.clear()
        copy.animation_data_clear()
        write_blend(output, {copy})
        return {"object": copy.name}
    finally:
        discard_new(existing)


def append_groom(context, target_surface, path, meta):
    base = figure_base(context, target_surface)
    uv = target_surface.data.uv_layers.active
    if uv is None:
        raise ValueError("Das Zielmesh braucht eine aktive UV-Map.")
    existing = set(bpy.data.user_map())
    try:
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            if meta["object"] not in source.objects:
                raise ValueError("Das gespeicherte Hair-Curves-Objekt fehlt.")
            target.objects = [meta["object"]]
        obj = target.objects[0]
        reference = obj.get(binding.MESH) if obj else None
        if obj is None or obj.type != "CURVES" or not isinstance(reference, bpy.types.Mesh):
            raise ValueError("Die gespeicherten Hair Curves enthalten keine Oberflächenbindung.")
        base_skin = binding_surface(base, base)
        destination = base_skin if base == target_surface else binding_surface(base, target_surface)
        source_skin = binding.Surface(reference, Matrix.Identity(4), -1)
        result = binding.transfer(obj, source_skin, base_skin, destination, Matrix.Identity(4), uv.name, None)
        context.collection.objects.link(obj)
        target_surface.add_rest_position_attribute = True
        binding.apply_transfer(obj, target_surface, uv.name, result)
        obj.name = meta["name"]
        obj[OWNER] = base
        if not any(mod.type == "NODES" and mod.node_group and
                   mod.node_group.name.startswith("MPFB-Tool Hair Modifier") for mod in obj.modifiers):
            add_hair_modifier(obj)
        context.view_layer.update()
        binding.remember_binding(context.scene, obj)
        if reference.users == 0:
            bpy.data.meshes.remove(reference)
        return obj
    except Exception:
        discard_new(existing)
        raise
