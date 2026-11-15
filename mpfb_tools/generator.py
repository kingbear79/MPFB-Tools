"""Create source files in a separate Blender process."""
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


def create_basis(category, output):
    from bl_ext.blender_org.mpfb.services import HumanService, LocationService, RigService

    preset = Path(LocationService.get_user_config("human.Basis-Bär.json"))
    if not preset.is_file():
        raise ValueError("Das MPFB-Preset „Basis-Bär“ wurde nicht gefunden.")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    settings = dict(mask_helpers=True, detailed_helpers=True, extra_vertex_groups=True,
                    feet_on_ground=True, scale=0.1, subdiv_levels=0, load_clothes=False,
                    material_instances=False)
    human = HumanService.deserialize_from_dict(json.loads(preset.read_text(encoding="utf-8")), settings)
    meta = HumanService.add_builtin_rig(human, "rigify.human_toes")
    RigService.generate_rigify_rig(meta)
    if category == "body":
        human.vertex_groups.new(name="Generator.Target.Position")
        bpy.ops.object.armature_add(enter_editmode=True)
        armature = bpy.context.object
        armature.name = "Körperteil-Armature"
        armature.data.edit_bones[0].name = "Root"
        bpy.ops.object.mode_set(mode="OBJECT")
        armature["Target Bone"] = "hips"
        bpy.ops.mesh.primitive_plane_add(size=.1)
        mesh = bpy.context.object
        mesh.name = "Körperteil"
        mesh.parent = armature
        mesh.matrix_parent_inverse = Matrix.Identity(4)
        group = mesh.vertex_groups.new(name="Root")
        group.add([v.index for v in mesh.data.vertices], 1, "REPLACE")
        mesh.modifiers.new("Armature", "ARMATURE").object = armature
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True)


if __name__ == "__main__":
    category, filename = sys.argv[sys.argv.index("--") + 1:]
    create_basis(category, Path(filename))
