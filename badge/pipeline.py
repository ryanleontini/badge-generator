"""Build orchestration: config -> geometry -> manifold check -> files."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import bpy

from . import base, booleans, export, scene
from .config import BadgeConfig
from .mesh import bounds, copy_object, triangle_count

log = logging.getLogger("badge")


@dataclass
class Build:
    base: bpy.types.Object
    full: bpy.types.Object
    outputs: dict[str, Path] = field(default_factory=dict)


def build_geometry(cfg: BadgeConfig) -> Build:
    """Reset the scene and build all bodies. Raises NonManifoldError on bad geometry."""
    collections = scene.prepare_scene()
    body = base.build_base(cfg, collections["Base"])
    booleans.cleanup(body)
    full = copy_object(body, f"{cfg.badge.name}_full", collections["Base"])
    booleans.require_manifold(body, full)
    return Build(base=body, full=full)


def export_outputs(cfg: BadgeConfig, build: Build) -> None:
    out, name = cfg.out_path, cfg.badge.name
    if cfg.export.single_body:
        build.outputs["full"] = export.export_stl([build.full], out / f"{name}_full.stl")
    if cfg.export.split_bodies:
        build.outputs["base"] = export.export_stl([build.base], out / f"{name}_base.stl")


def log_report(build: Build) -> None:
    lo, hi = bounds(build.full)
    size = [h - l for l, h in zip(lo, hi)]
    log.info("size: %.3f x %.3f x %.3f mm (X x Y x Z)", *size)
    for obj in (build.base, build.full):
        log.info("%-18s %7d triangles, %d non-manifold edges", obj.name,
                 triangle_count(obj), booleans.non_manifold_edges(obj))
    for label, path in build.outputs.items():
        log.info("wrote %-6s %s", label, path)
