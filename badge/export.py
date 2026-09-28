"""STL export and preview rendering."""

import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

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


PREVIEW_SIZE = 900  # px, per view
BASE_COLOR = (0.70, 0.72, 0.75, 1.0)
EMBLEM_COLOR = (0.86, 0.62, 0.16, 1.0)


def render_preview(bodies: list[bpy.types.Object], diameter: float, path: Path) -> Path:
    """Render a side-by-side PNG: orthographic top view | angled 3/4 view.

    Uses Workbench with per-object colors so the two print colors read clearly.
    ``bodies`` are shown; everything else in the scene is hidden from render.
    """
    scene = bpy.context.scene
    _setup_workbench(scene)
    for obj in scene.objects:
        obj.hide_render = obj not in bodies
    for obj, color in zip(bodies, (BASE_COLOR, EMBLEM_COLOR)):
        obj.color = color

    top = _camera("preview_top", scene)
    top.data.type = "ORTHO"
    top.data.ortho_scale = diameter * 1.08
    top.location = (0.0, 0.0, diameter)

    angled = _camera("preview_angled", scene)
    angled.data.lens = 50
    elevation, azimuth = math.radians(38), math.radians(-25)
    distance = diameter * 1.55
    angled.location = (distance * math.cos(elevation) * math.sin(azimuth),
                       -distance * math.cos(elevation) * math.cos(azimuth),
                       distance * math.sin(elevation))
    angled.rotation_euler = (-Vector(angled.location)).to_track_quat("-Z", "Y").to_euler()

    path.parent.mkdir(parents=True, exist_ok=True)
    views = []
    for cam in (top, angled):
        scene.camera = cam
        scene.render.filepath = str(path.with_name(f"{path.stem}_{cam.name}.png"))
        bpy.ops.render.render(write_still=True)
        views.append(Path(scene.render.filepath))
    _combine_side_by_side(views, path)
    for view in views:
        view.unlink()
    for cam in (top, angled):
        data = cam.data
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(data)
    return path


def _setup_workbench(scene: bpy.types.Scene) -> None:
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = scene.render.resolution_y = PREVIEW_SIZE
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 75
    scene.view_settings.view_transform = "Standard"
    scene.display.render_aa = "8"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"
    shading.show_cavity = True
    shading.cavity_type = "WORLD"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("preview")
    scene.world.color = (0.16, 0.17, 0.19)


def _camera(name: str, scene: bpy.types.Scene) -> bpy.types.Object:
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    cam.data.clip_start = 1.0
    cam.data.clip_end = 10000.0  # scene units are mm
    scene.collection.objects.link(cam)
    return cam


def _combine_side_by_side(views: list[Path], path: Path) -> None:
    images = [bpy.data.images.load(str(v)) for v in views]
    width, height = images[0].size
    rows = []
    for img in images:
        px = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        rows.append(px.reshape(height, width, 4))
    combined = np.concatenate(rows, axis=1)
    out = bpy.data.images.new(path.stem, width * len(images), height)
    out.pixels.foreach_set(combined.ravel())
    out.save_render(str(path), scene=bpy.context.scene)  # uses scene PNG settings
    for img in images + [out]:
        bpy.data.images.remove(img)
