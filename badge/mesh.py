"""Low-level bmesh helpers shared by the geometry modules."""

import math

import bmesh
import bpy

Profile = list[tuple[float, float]]  # (radius, z) points


def revolve(profile: Profile, segments: int) -> bmesh.types.BMesh:
    """Spin an (r, z) profile around the Z axis into a closed solid.

    The profile must start on the axis at the bottom, run outward and up, and
    end on the axis at the top. Points with r == 0 become single pole vertices,
    so the result is manifold by construction.
    """
    profile = _dedupe(profile)
    if profile[0][0] != 0 or profile[-1][0] != 0:
        raise ValueError("revolve profile must start and end on the axis (r == 0)")
    bm = bmesh.new()
    angles = [2 * math.pi * i / segments for i in range(segments)]
    rings = []
    for r, z in profile:
        if r == 0:
            rings.append([bm.verts.new((0.0, 0.0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for a in angles])
    for lo, hi in zip(rings, rings[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            if len(lo) == 1:
                bm.faces.new((lo[0], hi[i], hi[j]))
            elif len(hi) == 1:
                bm.faces.new((lo[i], lo[j], hi[0]))
            else:
                bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def extrude_flat(bm: bmesh.types.BMesh, z_bottom: float, z_top: float) -> None:
    """Turn flat (z == 0) filled faces into a closed prism spanning z_bottom..z_top."""
    for v in bm.verts:
        v.co.z = z_bottom
    ret = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
    top = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top, vec=(0.0, 0.0, z_top - z_bottom))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def to_object(bm: bmesh.types.BMesh, name: str,
              collection: bpy.types.Collection) -> bpy.types.Object:
    """Write ``bm`` into a new mesh object linked to ``collection`` and free it."""
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def copy_object(obj: bpy.types.Object, name: str,
                collection: bpy.types.Collection) -> bpy.types.Object:
    dup = bpy.data.objects.new(name, obj.data.copy())
    dup.data.name = name
    dup.matrix_world = obj.matrix_world
    collection.objects.link(dup)
    return dup


def triangle_count(obj: bpy.types.Object) -> int:
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def bounds(obj: bpy.types.Object) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """World-space (min, max) corners of the object's vertices."""
    mw = obj.matrix_world
    pts = [mw @ v.co for v in obj.data.vertices]
    return (tuple(min(p[i] for p in pts) for i in range(3)),
            tuple(max(p[i] for p in pts) for i in range(3)))


def _dedupe(profile: Profile, eps: float = 1e-6) -> Profile:
    out: Profile = []
    for p in profile:
        if not out or math.dist(p, out[-1]) > eps:
            out.append(p)
    return out
