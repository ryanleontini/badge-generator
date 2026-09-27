"""Blender version detection. API differences between versions are branched here."""

import bpy

MIN_VERSION = (4, 2, 0)
VERSION: tuple[int, int, int] = tuple(bpy.app.version)


def check_version() -> None:
    if VERSION < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        raise RuntimeError(f"Blender {need}+ required, running {bpy.app.version_string}")


def export_stl(filepath: str) -> None:
    """Export the selected objects as binary STL, 1 Blender unit = 1 mm."""
    if hasattr(bpy.ops.wm, "stl_export"):  # Blender 4.1+ native exporter
        bpy.ops.wm.stl_export(filepath=filepath, export_selected_objects=True,
                              apply_modifiers=True, global_scale=1.0,
                              use_scene_unit=False, ascii_format=False)
    else:  # legacy Python add-on exporter
        bpy.ops.export_mesh.stl(filepath=filepath, use_selection=True,
                                use_mesh_modifiers=True, global_scale=1.0,
                                use_scene_unit=False, ascii=False)
