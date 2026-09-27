"""Scene reset, millimeter units and output collections."""

import bpy

COLLECTIONS = ("Base", "Emblem", "Mounting")


def prepare_scene() -> dict[str, bpy.types.Collection]:
    """Reset to an empty mm-unit scene and return the pipeline collections by name."""
    _clear_data()
    scene = bpy.context.scene
    _set_mm_units(scene)
    collections = {}
    for name in COLLECTIONS:
        coll = bpy.data.collections.new(name)
        scene.collection.children.link(coll)
        collections[name] = coll
    return collections


def _clear_data() -> None:
    # Objects first so meshes/curves/etc. lose their users before removal.
    for store in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.collections,
    ):
        for block in list(store):
            store.remove(block)


def _set_mm_units(scene: bpy.types.Scene) -> None:
    units = scene.unit_settings
    units.system = "METRIC"
    units.scale_length = 0.001  # 1 Blender unit = 1 mm
    units.length_unit = "MILLIMETERS"
