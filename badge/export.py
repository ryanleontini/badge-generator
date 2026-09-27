"""STL export and preview rendering."""

from pathlib import Path

import bpy

from . import compat


def export_stl(objects: list[bpy.types.Object], path: Path) -> Path:
    """Export ``objects`` (world coordinates, mm) to one binary STL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    view_layer = bpy.context.view_layer
    view_layer.update()
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    view_layer.objects.active = objects[0]
    compat.export_stl(str(path))
    return path
