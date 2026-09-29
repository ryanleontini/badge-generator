"""Build orchestration: config -> geometry -> manifold check -> files."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import bpy

from . import base, booleans, emblem, export, mounting, ring, scene
from .config import BadgeConfig
from .mesh import bounds, copy_object, triangle_count

log = logging.getLogger("badge")


@dataclass
class Build:
    base: bpy.types.Object  # base disc + ring (+ mounting features)
    emblem: bpy.types.Object  # emblem trimmed to sit on the base without overlap
    full: bpy.types.Object  # base and emblem unioned into one body
    emblem_extent: float  # farthest emblem point from the center, mm
    outputs: dict[str, Path] = field(default_factory=dict)

    @property
    def bodies(self) -> list[bpy.types.Object]:
        return [self.base, self.emblem, self.full]


def build_geometry(cfg: BadgeConfig) -> Build:
    """Reset the scene and build all bodies. Raises NonManifoldError on bad geometry."""
    collections = scene.prepare_scene()
    ring_with_emblem = cfg.ring.enabled and cfg.ring.part == "emblem"
    body = _base_body(cfg, collections, with_ring=True)  # base + ring: the full shape

    # The extruded emblem is manifold by construction; merging by distance here
    # could re-fuse the pinch points emblem.py deliberately separated.
    raw_emblem = emblem.build_emblem(cfg, collections["Emblem"])
    booleans.require_manifold(raw_emblem)  # solvers may silently drop bad operands
    extent = emblem.emblem_extent(raw_emblem)

    # Single body: the emblem overlaps the base by OVERLAP so the union is clean.
    full = copy_object(body, f"{cfg.badge.name}_full", collections["Base"])
    booleans.apply_boolean(full, raw_emblem, "UNION")
    booleans.cleanup(full)

    # Split bodies touch without intersecting, which keeps two-color slicing
    # unambiguous. With ring.part = "emblem" the ring moves to the emblem part.
    if ring_with_emblem:
        _delete(body)  # first, so the ring-less base can take its name
        base_part = _base_body(cfg, collections, with_ring=False)
    else:
        base_part = body
    booleans.apply_boolean(raw_emblem, base_part, "DIFFERENCE")  # trim the overlap
    booleans.cleanup(raw_emblem)
    emblem_part = raw_emblem
    if ring_with_emblem:
        ring_solid = ring.build_ring(cfg, collections["Emblem"])
        booleans.apply_boolean(emblem_part, ring_solid, "UNION")
        booleans.cleanup(emblem_part)
        _delete(ring_solid)

    # Boolean solvers can silently drop an operand: the two parts must add up
    # to the single body.
    base_volume, emblem_volume = booleans.volume(base_part), booleans.volume(emblem_part)
    if emblem_volume <= 0 or abs(booleans.volume(full) - base_volume - emblem_volume) > \
            0.01 * (base_volume + emblem_volume):
        raise booleans.NonManifoldError("boolean lost geometry: full body volume != base + emblem")

    build = Build(base=base_part, emblem=emblem_part, full=full, emblem_extent=extent)
    booleans.require_manifold(*build.bodies)
    return build


def _base_body(cfg: BadgeConfig, collections: dict, with_ring: bool) -> bpy.types.Object:
    """Base disc (optionally with the ring) plus mounting features, cleaned."""
    body = base.build_base(cfg, collections["Base"], bottom=mounting.bottom_profile(cfg),
                           with_ring=with_ring)
    for pin in mounting.build_pins(cfg, collections["Mounting"]):
        booleans.apply_boolean(body, pin, "UNION")
        _delete(pin)
    booleans.cleanup(body)
    return body


def _delete(obj: bpy.types.Object) -> None:
    data = obj.data
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(data)


def export_outputs(cfg: BadgeConfig, build: Build) -> None:
    out, name = cfg.out_path, cfg.badge.name
    if cfg.export.single_body:
        build.outputs["full"] = export.export_stl([build.full], out / f"{name}_full.stl")
    if cfg.export.split_bodies:
        build.outputs["base"] = export.export_stl([build.base], out / f"{name}_base.stl")
        build.outputs["emblem"] = export.export_stl([build.emblem], out / f"{name}_emblem.stl")
    if cfg.export.render_preview:
        build.outputs["preview"] = export.render_preview(
            [build.base, build.emblem], cfg.badge.diameter, out / f"{name}_preview.png")


def log_report(cfg: BadgeConfig, build: Build) -> None:
    lo, hi = bounds(build.full)
    size = [h - l for l, h in zip(lo, hi)]
    log.info("size: %.3f x %.3f x %.3f mm (X x Y x Z)", *size)
    bound = cfg.ring_inner_radius if cfg.ring.enabled else cfg.emblem_area_radius
    gap = bound - build.emblem_extent
    if cfg.emblem_touches_ring:
        log.info("emblem reaches r = %.2f mm; fused %.2f mm into the ring",
                 build.emblem_extent, -gap)
    else:
        log.info("emblem reaches r = %.2f mm; clearance to %s %.2f mm", build.emblem_extent,
                 "ring" if cfg.ring.enabled else "edge", gap)
    for obj in build.bodies:
        log.info("%-20s %7d triangles, %d non-manifold edges", obj.name,
                 triangle_count(obj), booleans.non_manifold_edges(obj))
    for label, path in build.outputs.items():
        log.info("wrote %-7s %s", label, path)
