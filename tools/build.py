"""Build a Blender Extension from the explicitly shipped source files."""
import argparse
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--output", default="dist")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "mpfb_tools"
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = tomllib.loads((source / "blender_manifest.toml").read_text())
    version = manifest["version"]
    parsed = ast.parse((source / "__init__.py").read_text())
    info = next(ast.literal_eval(node.value) for node in parsed.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "bl_info" for target in node.targets))
    if ".".join(map(str, info["version"])) != version:
        raise ValueError("Manifest and add-on version differ.")
    tag = os.environ.get("GITHUB_REF_NAME")
    if tag and os.environ.get("GITHUB_REF_TYPE") == "tag" and tag != f"v{version}":
        raise ValueError("Release tag does not match the manifest.")
    with tempfile.TemporaryDirectory(prefix="mpfb-build-") as folder:
        staging = Path(folder)
        allowed = [Path("blender_manifest.toml")]
        allowed.extend(path.relative_to(source) for path in source.glob("*.py"))
        allowed.extend(Path("defaults") / name for name in
                       ("hair_groups.json", "hair_modifier.blend", "basis_baer.json"))
        allowed.extend(path.relative_to(source) for path in (source / "defaults" / "grooms").glob("*.png")
                       if re.fullmatch("[HBA][0-9]{2}\\.png", path.name))
        for path in allowed:
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / path, target)
        shutil.copyfile(root / "LICENSE", staging / "LICENSE")
        subprocess.run([args.blender, "--command", "extension", "build",
                        "--source-dir", str(staging), "--output-dir", str(output)], check=True)
        subprocess.run([args.blender, "--command", "extension", "server-generate",
                        "--repo-dir", str(output), "--html"], check=True)


if __name__ == "__main__":
    main()
