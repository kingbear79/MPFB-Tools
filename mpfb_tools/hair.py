"""Create editable hair surfaces that evaluate from the final body mesh."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix


REGIONS = (("__HAARE", "Haare"), ("__BART", "Bart"))
TEMPLATE = Path(__file__).parent / "defaults" / "hair_groups.json"
HAIR_MODIFIER_NAME = "MPFB-Tool Hair Modifier"
HAIR_MODIFIER_LIBRARY = TEMPLATE.with_name("hair_modifier.blend")


def add_hair_modifier(curves, *, frizz_distance=None):
    group = bpy.data.node_groups.get(HAIR_MODIFIER_NAME)
    if group is None:
        with bpy.data.libraries.load(str(HAIR_MODIFIER_LIBRARY), link=False) as (source, loaded):
            if HAIR_MODIFIER_NAME not in source.node_groups:
                raise RuntimeError(f"Die Node-Gruppe „{HAIR_MODIFIER_NAME}“ fehlt in der Bibliothek.")
            loaded.node_groups = [HAIR_MODIFIER_NAME]
        group = loaded.node_groups[0]
    if group is None or group.bl_idname != "GeometryNodeTree":
        raise RuntimeError(f"„{HAIR_MODIFIER_NAME}“ ist keine Geometry-Nodes-Gruppe.")
    mesh_socket = next((item for item in group.interface.items_tree
                        if item.item_type == "SOCKET" and item.in_out == "INPUT"
                        and item.name == "Mesh erzeugen" and item.socket_type == "NodeSocketBool"), None)
    if mesh_socket is None:
        raise RuntimeError(f"Der Eingang „Mesh erzeugen“ fehlt in „{HAIR_MODIFIER_NAME}“.")
    modifier = curves.modifiers.new(HAIR_MODIFIER_NAME, "NODES")
    modifier.node_group = group
    modifier[mesh_socket.identifier] = False
    # Match the settings on the example hairstyle in the source file.
    for item in group.interface.items_tree:
        if item.item_type != "SOCKET" or item.in_out != "INPUT":
            continue
        if item.name == "Duplikate" and item.socket_type == "NodeSocketInt":
            modifier[item.identifier] = 0
        elif (frizz_distance is not None and item.name == "Frizz-Abstand"
              and item.socket_type == "NodeSocketFloat"):
            modifier[item.identifier] = frizz_distance


def object_type(obj):
    return (obj.get("MPFB_GEN_object_type") or obj.get("MhObjectType") or "").lower()


def body_surface(context, selected):
    if object_type(selected) != "basemesh":
        return selected
    rig = selected.parent
    proxies = [
        obj for obj in context.scene.objects
        if obj.type == "MESH" and object_type(obj) in {"proxymesh", "proxymeshes"}
        and (obj.parent == selected or (rig is not None and obj.parent == rig))
    ]
    visible = [obj for obj in proxies if obj.visible_get()]
    candidates = visible or proxies
    if len(candidates) > 1:
        raise ValueError("Mehrere Topology-Assets gefunden. Wähle das gewünschte Mesh direkt aus.")
    return candidates[0] if candidates else selected


def region_weights(surface):
    reference = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    weights = {
        name: {int(index): weight for index, weight in reference[name].items()}
        for name, _ in REGIONS
    }
    if object_type(surface) in {"proxymesh", "proxymeshes"}:
        try:
            from bl_ext.blender_org.mpfb.services import ClothesService
            from bl_ext.blender_org.mpfb.entities.clothes.mhclo import Mhclo
        except ImportError as error:
            raise ValueError("Für die Zuordnung des Topology-Assets muss MPFB2 verfügbar sein.") from error
        path = ClothesService.find_clothes_absolute_path(surface)
        if not path:
            raise ValueError("Die MPFB-Quelldatei des Topology-Assets wurde nicht gefunden.")
        mapping = Mhclo()
        mapping.load(path)
        if set(mapping.verts) != set(range(len(surface.data.vertices))):
            raise ValueError("Das Topology-Mesh passt nicht mehr zur MPFB-Quelldatei.")
        projected = {}
        for name, mask in weights.items():
            projected[name] = {}
            for index, entry in mapping.verts.items():
                weight = sum(mask.get(vertex, 0.0) * factor
                             for vertex, factor in zip(entry["verts"], entry["weights"]))
                if weight >= 0.5:
                    projected[name][index] = min(1.0, weight)
        return projected

    signature = hashlib.sha256(str([tuple(p.vertices) for p in surface.data.polygons]).encode()).hexdigest()
    if signature != reference["topology"]:
        raise ValueError("Das Mesh passt weder zur MPFB-Basemesh-Vorlage noch zu einem MPFB-Topology-Asset.")
    return weights


def add_live_surface(patch, source, attribute):
    modifier = patch.modifiers.new("Figurenoberfläche folgen", "NODES")
    tree = bpy.data.node_groups.new("MPFB-Tools · Haarfläche", "GeometryNodeTree")
    modifier.node_group = tree
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    source_node = tree.nodes.new("GeometryNodeObjectInfo")
    source_node.transform_space = "RELATIVE"
    source_node.inputs["Object"].default_value = source
    region = tree.nodes.new("GeometryNodeInputNamedAttribute")
    region.data_type = "BOOLEAN"
    region.inputs["Name"].default_value = attribute
    invert = tree.nodes.new("FunctionNodeBooleanMath")
    invert.operation = "NOT"
    cut = tree.nodes.new("GeometryNodeDeleteGeometry")
    cut.domain = "FACE"
    output = tree.nodes.new("NodeGroupOutput")
    source_node.location = (-450, 100)
    region.location = (-450, -130)
    invert.location = (-220, -130)
    cut.location = (0, 100)
    output.location = (220, 100)
    tree.links.new(source_node.outputs["Geometry"], cut.inputs["Geometry"])
    tree.links.new(region.outputs["Attribute"], invert.inputs[0])
    tree.links.new(invert.outputs[0], cut.inputs["Selection"])
    tree.links.new(cut.outputs["Geometry"], output.inputs["Geometry"])


def make_patch(context, source, name, weights, attribute):
    mesh = patch_mesh(source, weights)
    patch = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(patch)
    patch.parent = source
    patch.matrix_parent_inverse = Matrix.Identity(4)
    patch.hide_render = True
    patch.add_rest_position_attribute = True
    add_live_surface(patch, source, attribute)
    return patch


def patch_mesh(source, weights):
    mesh = source.data.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.delete(
            bm, geom=[vert for vert in bm.verts if vert.index not in weights],
            context="VERTS",
        )
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return mesh


def create_hair(context, selected):
    from .hair_binding import remember_binding

    surface = body_surface(context, selected)
    if surface.data.uv_layers.active is None:
        raise ValueError("Das endgültige Mesh braucht eine aktive UV-Map.")
    if any(obj.get("mpfb_tools_hair_surface") for obj in surface.children):
        raise ValueError("Für dieses Mesh sind bereits Haarflächen vorhanden.")

    masks = region_weights(surface)
    faces = {}
    for name, _ in REGIONS:
        faces[name] = [all(index in masks[name] for index in poly.vertices)
                       for poly in surface.data.polygons]
        if not any(faces[name]):
            raise ValueError(f"Für {name} wurden keine vollständigen Faces gefunden.")

    existing = set(bpy.data.user_map())
    previous_mesh = surface.data
    separate_mesh = previous_mesh.users > 1 and any(
        obj != surface and obj.type == "MESH" and obj.data == previous_mesh for obj in bpy.data.objects)
    rest_position = surface.add_rest_position_attribute
    attributes = []
    groups = []
    previous_weights = {}
    selection = list(context.selected_objects)
    try:
        if separate_mesh:
            surface.data = previous_mesh.copy()
        surface.add_rest_position_attribute = True
        for group_name, label in REGIONS:
            group = surface.vertex_groups.get(group_name)
            if group is None:
                group = surface.vertex_groups.new(name=group_name)
                groups.append(group)
            else:
                previous_weights[group_name] = {
                    vertex.index: entry.weight
                    for vertex in surface.data.vertices for entry in vertex.groups
                    if entry.group == group.index
                }
                group.remove(list(previous_weights[group_name]))
            by_weight = defaultdict(list)
            for index, weight in masks[group_name].items():
                by_weight[weight].append(index)
            for weight, indices in by_weight.items():
                group.add(indices, weight, "REPLACE")

            attribute = surface.data.attributes.new(
                name=f"mpfb_tools_{group_name[2:].lower()}", type="BOOLEAN", domain="FACE",
            )
            attributes.append(attribute)
            attribute.data.foreach_set("value", faces[group_name])
            patch = make_patch(context, surface, f"{selected.name}.Hair.{label}",
                               masks[group_name], attribute.name)
            patch["mpfb_tools_hair_surface"] = True
            patch["mpfb_tools_hair_region"] = group_name
            bpy.ops.object.select_all(action="DESELECT")
            patch.select_set(True)
            context.view_layer.objects.active = patch
            context.view_layer.update()
            if bpy.ops.object.curves_empty_hair_add() != {"FINISHED"}:
                raise RuntimeError(f"Empty Hair für {label} konnte nicht angelegt werden.")
            curves = context.active_object
            curves.name = label
            curves.data.name = label
            if curves.data.surface != patch:
                raise RuntimeError(f"Die Hair Curves für {label} sind nicht mit ihrer Haarfläche verbunden.")
            add_hair_modifier(curves)
            remember_binding(context.scene, curves)
    except Exception:
        for attribute in attributes:
            surface.data.attributes.remove(attribute)
        for group in groups:
            surface.vertex_groups.remove(group)
        for name, weights in previous_weights.items():
            group = surface.vertex_groups[name]
            group.remove(list(masks[name]))
            for index, weight in weights.items():
                group.add([index], weight, "REPLACE")
        surface.add_rest_position_attribute = rest_position
        if separate_mesh:
            surface.data = previous_mesh
        bpy.data.batch_remove(set(bpy.data.user_map()) - existing)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selection:
            obj.select_set(True)
        context.view_layer.objects.active = selected
        raise
    return surface


class MPFBTOOLS_OT_create_hair(bpy.types.Operator):
    bl_idname = "mpfb_tools.create_hair"
    bl_label = "Haare und Bart vorbereiten"
    bl_description = "Legt zwei Haarflächen und leere Hair Curves auf der endgültigen Körperoberfläche an"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        try:
            from .saved_assets import select_figure

            selected = context.active_object
            surface = create_hair(context, selected)
            select_figure(context, selected)
        except (OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Haare und Bart für {surface.name} vorbereitet")
        return {"FINISHED"}
