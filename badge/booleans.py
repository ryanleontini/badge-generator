"""Boolean helpers, mesh cleanup and the manifold check."""

import logging

import bmesh
import bpy

log = logging.getLogger("badge")

MERGE_DISTANCE = 0.001  # mm


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
    """Merge by distance, drop degenerate/loose geometry, recalc normals outward."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=MERGE_DISTANCE)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=MERGE_DISTANCE / 10)
    loose_edges = [e for e in bm.edges if not e.link_faces]
    bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    loose_verts = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def non_manifold_edges(obj: bpy.types.Object) -> int:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    count = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return count


class NonManifoldError(RuntimeError):
    pass


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
