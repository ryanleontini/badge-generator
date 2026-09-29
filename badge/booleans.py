"""Boolean helpers, mesh cleanup and the manifold check."""

import logging

import bmesh
import bpy

log = logging.getLogger("badge")

# Only fuses true duplicates. Traced SVG art can have real edges ~0.002 mm long;
# a coarser merge (e.g. 0.001 mm) collapses them and breaks manifoldness.
MERGE_DISTANCE = 1e-5  # mm


def solver() -> str:
    """MANIFOLD (Blender 4.5+) when available, else EXACT."""
    prop = bpy.types.BooleanModifier.bl_rna.properties["solver"]
    return "MANIFOLD" if "MANIFOLD" in {i.identifier for i in prop.enum_items} else "EXACT"


def apply_boolean(target: bpy.types.Object, cutter: bpy.types.Object, operation: str) -> None:
    """Apply ``target <operation> cutter`` in place (operation: UNION / DIFFERENCE / INTERSECT).

    Evaluates the modifier through the depsgraph instead of bpy.ops.modifier_apply,
    which avoids context requirements when running headless.
    """
    mod = target.modifiers.new("boolean", "BOOLEAN")
    mod.operation = operation
    mod.solver = solver()
    mod.object = cutter
    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = bpy.data.meshes.new_from_object(target.evaluated_get(depsgraph))
    target.modifiers.remove(mod)
    old = target.data
    result.name = old.name
    target.data = result
    bpy.data.meshes.remove(old)


def cleanup(obj: bpy.types.Object) -> None:
    """Merge duplicates, drop degenerate/loose geometry, recalc normals outward.

    Merging is skipped if it would add non-manifold edges: on very fine meshes
    (traced art) it can fuse distinct points that the solver kept apart.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before = _count_non_manifold(bm)
    merged = bm.copy()
    bmesh.ops.remove_doubles(merged, verts=merged.verts[:], dist=MERGE_DISTANCE)
    bmesh.ops.dissolve_degenerate(merged, edges=merged.edges[:], dist=MERGE_DISTANCE / 10)
    if _count_non_manifold(merged) <= before:
        bm.free()
        bm = merged
    else:
        merged.free()
        log.debug("%s: skipped merge by distance (would break manifoldness)", obj.name)
    loose_edges = [e for e in bm.edges if not e.link_faces]
    bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    loose_verts = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _count_non_manifold(bm: bmesh.types.BMesh) -> int:
    return sum(1 for e in bm.edges if not e.is_manifold)


def non_manifold_edges(obj: bpy.types.Object) -> int:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    count = _count_non_manifold(bm)
    bm.free()
    return count


class NonManifoldError(RuntimeError):
    pass


def volume(obj: bpy.types.Object) -> float:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    vol = bm.calc_volume(signed=True)
    bm.free()
    return vol


def require_manifold(*objects: bpy.types.Object) -> None:
    """Log each object's manifold status; raise if any has non-manifold edges."""
    bad = []
    for obj in objects:
        count = non_manifold_edges(obj)
        log.debug("%s: %d non-manifold edges", obj.name, count)
        if count:
            bad.append(f"{obj.name} ({count} edges)")
    if bad:
        raise NonManifoldError("non-manifold geometry: " + ", ".join(bad))
