"""Emblem geometry: SVG paths or text -> filled 2D shape -> fitted, extruded solid.

Both modes produce flat filled curves that go through the same steps:

1. Tessellate the filled 2D curve into faces (holes/counters respected).
2. Fit: center the bounding box on the origin and scale uniformly so the
   farthest point lies on a circle of ``cfg.emblem_max_radius``. Fitting the
   bounding *circle* (not box) guarantees the emblem clears the ring at any
   rotation. SVG units/DPI are never trusted.
3. Rotate, offset, and extrude from just below the base top face to
   ``relief`` above its highest point.
"""

import logging
import math
from pathlib import Path

import addon_utils
import bmesh
import bpy
from mathutils import Matrix, Vector

from . import base
from .config import OVERLAP, BadgeConfig
from .mesh import extrude_flat, to_object

log = logging.getLogger("badge")

CURVE_RESOLUTION = 24  # bezier subdivisions per segment


class EmblemError(RuntimeError):
    pass


def build_emblem(cfg: BadgeConfig, collection: bpy.types.Collection) -> bpy.types.Object:
    if cfg.emblem.mode == "svg":
        curve = _import_svg(cfg.svg_file, collection)
    else:
        curve = _make_text(cfg, collection)
    bm = _tessellate(curve)
    _fit(bm, cfg)
    extrude_flat(bm, cfg.badge.base_thickness - OVERLAP,
                 base.field_peak(cfg) + cfg.emblem.relief)
    return to_object(bm, f"{cfg.badge.name}_emblem", collection)


def emblem_extent(obj: bpy.types.Object) -> float:
    """Farthest distance of any emblem vertex from the disc center (mm)."""
    return max(math.hypot(v.co.x, v.co.y) for v in obj.data.vertices)


def _import_svg(path: Path, collection: bpy.types.Collection) -> bpy.types.Object:
    _enable_svg_importer()
    objects_before = set(bpy.data.objects)
    collections_before = set(bpy.data.collections)
    bpy.ops.import_curve.svg(filepath=str(path))
    imported = [o for o in bpy.data.objects if o not in objects_before]
    curves = [o for o in imported if o.type == "CURVE"]
    if not curves:
        raise EmblemError(f"{path.name}: no paths found in SVG")

    merged = _merge_curves(curves, f"{path.stem}_curves", collection)
    for obj in imported:
        data = obj.data
        bpy.data.objects.remove(obj)
        if isinstance(data, bpy.types.Curve) and data.users == 0:
            bpy.data.curves.remove(data)
    for coll in set(bpy.data.collections) - collections_before:
        bpy.data.collections.remove(coll)  # the importer's per-file collection
    return merged


def _enable_svg_importer() -> None:
    try:
        module = addon_utils.enable("io_curve_svg", default_set=True)
    except Exception as exc:  # add-on present but failed to register
        raise EmblemError(f"could not enable the SVG importer (io_curve_svg): {exc}") from exc
    if module is None or "svg" not in dir(bpy.ops.import_curve):
        raise EmblemError("the SVG importer add-on (io_curve_svg) is not available in "
                          "this Blender build; use emblem.mode = 'text' or install it")


def _merge_curves(objects: list[bpy.types.Object], name: str,
                  collection: bpy.types.Collection) -> bpy.types.Object:
    """Copy every spline (in world space) into one 2D filled curve.

    Filling all splines together is what turns inner contours into holes.
    """
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.resolution_u = CURVE_RESOLUTION
    open_paths = 0
    for obj in objects:
        mw = obj.matrix_world
        for src in obj.data.splines:
            open_paths += not src.use_cyclic_u
            dst = curve.splines.new(src.type)
            dst.use_cyclic_u = src.use_cyclic_u
            dst.resolution_u = CURVE_RESOLUTION
            if src.type == "BEZIER":
                dst.bezier_points.add(len(src.bezier_points) - 1)
                for s, d in zip(src.bezier_points, dst.bezier_points):
                    d.handle_left_type, d.handle_right_type = s.handle_left_type, s.handle_right_type
                    d.co = mw @ s.co
                    d.handle_left = mw @ s.handle_left
                    d.handle_right = mw @ s.handle_right
            else:
                dst.points.add(len(src.points) - 1)
                for s, d in zip(src.points, dst.points):
                    d.co = (*(mw @ s.co.xyz), s.co.w)
    if open_paths:
        log.warning("SVG has %d open path(s); only closed paths are filled", open_paths)
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    return obj


def _make_text(cfg: BadgeConfig, collection: bpy.types.Collection) -> bpy.types.Object:
    curve = bpy.data.curves.new(f"{cfg.badge.name}_text", "FONT")
    curve.body = cfg.emblem.text
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.fill_mode = "BOTH"
    curve.resolution_u = CURVE_RESOLUTION
    if cfg.font_file:
        try:
            curve.font = bpy.data.fonts.load(str(cfg.font_file), check_existing=True)
        except RuntimeError as exc:
            raise EmblemError(f"could not load font {cfg.font_file}: {exc}") from exc
    obj = bpy.data.objects.new(curve.name, curve)
    collection.objects.link(obj)
    return obj


def _tessellate(curve_obj: bpy.types.Object) -> bmesh.types.BMesh:
    """Evaluate the filled curve into a flat bmesh at z = 0 and delete the curve."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(curve_obj.evaluated_get(depsgraph))
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.transform(curve_obj.matrix_world)
    data = curve_obj.data
    bpy.data.objects.remove(curve_obj)
    bpy.data.curves.remove(data)
    bpy.data.meshes.remove(mesh)

    loose = [e for e in bm.edges if not e.link_faces]  # unfilled open paths
    bmesh.ops.delete(bm, geom=loose, context="EDGES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    if not bm.faces:
        bm.free()
        raise EmblemError("emblem has no filled area: SVG paths must be closed shapes and "
                          "text must contain glyphs the font can draw")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
    for v in bm.verts:
        v.co.z = 0.0
    return bm


def _fit(bm: bmesh.types.BMesh, cfg: BadgeConfig) -> None:
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    center = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, 0.0))
    extent = max((v.co - center).length for v in bm.verts)
    if extent <= 0:
        raise EmblemError("emblem has zero size")
    em = cfg.emblem
    matrix = (Matrix.Translation((em.offset_x, em.offset_y, 0.0))
              @ Matrix.Rotation(math.radians(em.rotation_deg), 4, "Z")
              @ Matrix.Scale(cfg.emblem_max_radius / extent, 4)
              @ Matrix.Translation(-center))
    bm.transform(matrix)
