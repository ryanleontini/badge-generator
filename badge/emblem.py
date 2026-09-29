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
from .booleans import MERGE_DISTANCE
from .config import OVERLAP, BadgeConfig
from .mesh import extrude_flat, to_object

log = logging.getLogger("badge")

CURVE_RESOLUTION = 24  # bezier subdivisions per segment
TARGET_CHORD = 0.1  # mm; curve sampling step at print scale (well under a 0.4 mm nozzle)
PINCH_GAP = 0.01  # mm each side; separates shapes that touch at a single point
MAX_REPAIR_AREA = 0.05  # mm^2; larger overlapping fill faces are real overlaps, not debris
MAX_OVERLAP_REPAIRS = 100
FILL_AREA_TOLERANCE = 0.01  # filled vs. expected area; larger gaps mean crossing paths


class EmblemError(RuntimeError):
    pass


def build_emblem(cfg: BadgeConfig, collection: bpy.types.Collection) -> bpy.types.Object:
    if cfg.emblem.mode == "svg":
        curve = _import_svg(cfg.svg_file, collection)
        _adapt_resolution(curve.data, cfg.emblem_max_radius)
    else:
        curve = _make_text(cfg, collection)
    bm = _tessellate(curve)
    _fit(bm, cfg)
    _repair_outline(bm)
    _separate_pinches(bm)
    _require_clean_outline(bm)
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


def _adapt_resolution(curve: bpy.types.Curve, fit_radius: float) -> None:
    """Sample each spline at ~TARGET_CHORD at final print size.

    A fixed resolution over-samples traced art (thousands of tiny segments)
    into points ~0.001 mm apart, which slicers weld together into broken
    geometry, and under-samples long smooth curves.
    """
    points = [p.co for s in curve.splines for p in s.bezier_points]
    if not points:
        return
    xs, ys = [p.x for p in points], [p.y for p in points]
    center = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, 0.0))
    extent = max((p.xy - center.xy).length for p in points)
    if extent <= 0:
        return
    scale = fit_radius / extent  # approximate; the exact fit happens after tessellation
    for spline in curve.splines:
        pts = spline.bezier_points
        if len(pts) < 2:
            continue
        pairs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if spline.use_cyclic_u else [])
        # Control-polygon length bounds the arc length of each segment from above.
        mean = sum((a.co - a.handle_right).length + (a.handle_right - b.handle_left).length
                   + (b.handle_left - b.co).length for a, b in pairs) / len(pairs)
        spline.resolution_u = max(1, min(CURVE_RESOLUTION, math.ceil(mean * scale / TARGET_CHORD)))


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
    expected = _expected_fill_area(curve_obj)
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
    filled = sum(f.calc_area() for f in bm.faces)
    if abs(filled - expected) > FILL_AREA_TOLERANCE * expected:
        bm.free()
        raise EmblemError("emblem paths overlap or cross each other, so they can't be filled "
                          "reliably; merge them into one shape first (Figma: Union then "
                          "Flatten; Inkscape: Path > Union) and try again")
    return bm


def _expected_fill_area(curve_obj: bpy.types.Object) -> float:
    """Area the closed outlines should enclose (even-odd nesting), from the raw contours.

    Blender fills non-crossing contours correctly; crossing or overlapping ones
    give a different area. Comparing the two catches that before it prints wrong.
    """
    curve = curve_obj.data
    fill_mode = curve.fill_mode
    curve.fill_mode = "NONE"
    depsgraph = bpy.context.evaluated_depsgraph_get()
    wire = bpy.data.meshes.new_from_object(curve_obj.evaluated_get(depsgraph))
    curve.fill_mode = fill_mode
    mw = curve_obj.matrix_world
    contours = _closed_loops(wire, mw)
    bpy.data.meshes.remove(wire)

    total = 0.0
    boxes = [_bbox(c) for c in contours]
    for i, contour in enumerate(contours):
        x, y = contour[0]
        depth = sum(1 for j, other in enumerate(contours)
                    if j != i and _in_box(x, y, boxes[j]) and _point_in_polygon(x, y, other))
        total += abs(_shoelace(contour)) * (1 if depth % 2 == 0 else -1)
    return total


def _closed_loops(mesh: bpy.types.Mesh, matrix: Matrix) -> list[list[tuple[float, float]]]:
    """Closed vertex chains of a wire mesh, in world XY. Open chains are skipped."""
    neighbors: dict[int, list[int]] = {}
    for e in mesh.edges:
        a, b = e.vertices
        neighbors.setdefault(a, []).append(b)
        neighbors.setdefault(b, []).append(a)
    coords = [(matrix @ v.co).xy for v in mesh.vertices]
    seen, loops = set(), []
    for start, adj in neighbors.items():
        if start in seen or len(adj) != 2:
            continue
        loop, prev, cur = [], None, start
        while cur not in seen:
            seen.add(cur)
            loop.append(tuple(coords[cur]))
            nxt = [n for n in neighbors[cur] if n != prev and len(neighbors[n]) == 2]
            if not nxt:
                loop = []  # dead end: open path
                break
            prev, cur = cur, nxt[0]
        if len(loop) >= 3 and cur == start:
            loops.append(loop)
    return loops


def _shoelace(pts: list[tuple[float, float]]) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _in_box(x, y, box) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _point_in_polygon(x: float, y: float, pts: list[tuple[float, float]]) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _repair_outline(bm: bmesh.types.BMesh) -> None:
    """Remove fill debris where contours nearly touch (common in traced SVGs).

    Blender's 2D fill can leave zero-area slivers and small back-facing
    triangles there. They are far below print resolution but make the
    extruded solid non-manifold, which boolean solvers may silently discard.
    """
    # Merge at the same distance the final cleanup uses, so no new pinch points
    # can appear after _separate_pinches has run.
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=MERGE_DISTANCE)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-4)
    bm.normal_update()
    debris = [f for f in bm.faces if f.normal.z <= 0 or f.calc_area() < 1e-8]
    _delete_faces(bm, debris)
    # Where two contours overlap, fill triangles stack up on a shared edge.
    # Drop the smallest stacked triangle until every edge borders at most two.
    removed = len(debris)
    for _ in range(MAX_OVERLAP_REPAIRS):
        stacked = next((e for e in bm.edges if len(e.link_faces) > 2), None)
        if stacked is None:
            break
        smallest = min(stacked.link_faces, key=lambda f: f.calc_area())
        if smallest.calc_area() > MAX_REPAIR_AREA:
            break  # a real overlap, not debris: let _require_clean_outline report it
        _delete_faces(bm, [smallest])
        removed += 1
    if removed:
        log.info("repaired %d tiny fill artifact(s) in the emblem outline", removed)


def _delete_faces(bm: bmesh.types.BMesh, faces: list) -> None:
    if not faces:
        return
    bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")


def _require_clean_outline(bm: bmesh.types.BMesh) -> None:
    """Every edge of the flat shape must border one face (outline) or two (interior)."""
    bad = [e for e in bm.edges if len(e.link_faces) > 2]
    if bad:
        x, y = (bad[0].verts[0].co.x, bad[0].verts[0].co.y)
        raise EmblemError(f"emblem outline overlaps itself near ({x:.1f}, {y:.1f}) mm from "
                          f"the badge center; merge overlapping shapes in the SVG "
                          f"(e.g. Path > Union) and try again")


def _separate_pinches(bm: bmesh.types.BMesh) -> None:
    """Split vertices where two filled regions touch at a single point.

    Such a pinch (e.g. two glyph corners meeting) extrudes into an edge shared
    by four faces, which is non-manifold. Each copy is pulled PINCH_GAP into
    its own region, far below print resolution.
    """
    pinches = [v for v in bm.verts
               if sum(1 for e in v.link_edges if len(e.link_faces) == 1) > 2]
    for vert in pinches:
        boundary = [e for e in vert.link_edges if len(e.link_faces) == 1]
        for copy in bmesh.utils.vert_separate(vert, boundary):
            inward = sum((f.calc_center_median() - copy.co for f in copy.link_faces), Vector())
            if inward.length > 0:
                copy.co += inward.normalized() * PINCH_GAP
    if pinches:
        log.debug("separated %d pinch point(s) in the emblem outline", len(pinches))


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
