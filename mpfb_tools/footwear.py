"""Append a rigged shoe mesh and connect its existing weights to the target rig."""

import bpy


from .hair import object_type
from .library import SHOE_OBJECT, discard_new, load_objects
from .shoe_fit import REFERENCE, fit_shoes, store_reference


def append_boots(context, filepath, rig, report=None):
    existing = set(bpy.data.user_map())
    try:
        objects = load_objects(filepath, "shoes", inspect=True)
        boots = objects[SHOE_OBJECT]
        if boots is None or boots.type != "MESH":
            raise ValueError("Das Schuhobjekt konnte nicht als Mesh geladen werden.")
        modifiers = [modifier for modifier in boots.modifiers if modifier.type == "ARMATURE"]
        if not modifiers:
            raise ValueError("Die Schuhe benötigen ihren Armature-Modifier aus der Vorlage.")

        weighted = {
            boots.vertex_groups[group.group].name
            for vertex in boots.data.vertices for group in vertex.groups if group.weight > 0
            if boots.vertex_groups[group.group].name.startswith("DEF-")
        }
        missing = sorted(name for name in weighted if name not in rig.data.bones or not rig.data.bones[name].use_deform)
        if not weighted or missing:
            details = ", ".join(missing)
            raise ValueError(f"Das Zielrig unterstützt die Schuhgewichte nicht. {details}".strip())

        reference_rig = boots.parent or modifiers[0].object
        bodies = [obj for obj in objects.values()
                  if obj and obj.type == "MESH" and object_type(obj) == "basemesh"]
        associated = [obj for obj in bodies if obj.parent == reference_rig]
        if len(associated) == 1:
            bodies = associated
        if len(bodies) == 1 and reference_rig is not None:
            store_reference(boots, bodies[0], reference_rig)
        elif report:
            report({"WARNING"}, "Die Vorlage enthält keinen eindeutigen MPFB-Referenzkörper. Die Schuhe behalten ihre Vorlagenmaße.")

        context.collection.objects.link(boots)
        # The body in the editable file can still be connected to the reference rig.
        # Reuse the original parent-relative transform, including its scale and offset.
        if boots.parent is not None and (boots.parent.type != "ARMATURE" or boots.parent_type != "OBJECT"):
            raise ValueError("Die Schuhvorlage braucht ein Armature-Objekt als Parent.")
        boots.parent = rig
        for modifier in modifiers:
            modifier.object = rig

        if REFERENCE in boots:
            fit_shoes(context, boots)
        discard_new(existing, [boots])

        context.view_layer.update()
        return boots
    except Exception:
        discard_new(existing)
        raise
