"""Base disc with edge treatment, built as one lathe profile (including the ring).

Profile, from the bottom center outward and back to the top center:

    bottom face -> outer wall -> edge (flat / chamfer) -> ring -> field (flat / dome)

The bottom is always flat (it mounts against the car). Revolving a single
profile makes the base + ring body manifold by construction, no booleans.
"""

import bpy

from . import ring
from .config import BadgeConfig
from .mesh import Profile, revolve, to_object

DOME_STEPS = 32  # profile samples across a domed field


def build_base(cfg: BadgeConfig, collection: bpy.types.Collection,
               bottom: Profile | None = None) -> bpy.types.Object:
    """Build the base + ring body. ``bottom`` overrides the flat bottom profile
    (used for the tape recess); it must run from (0, z) out to (radius, 0)."""
    profile = (bottom or [(0.0, 0.0), (cfg.radius, 0.0)]) + _top_profile(cfg)
    return to_object(revolve(profile, cfg.badge.segments), f"{cfg.badge.name}_base", collection)


def field_height(cfg: BadgeConfig, r: float) -> float:
    """Z of the top face at radius ``r`` inside the ring (or the whole top if no ring)."""
    t = cfg.badge.base_thickness
    if cfg.badge.edge_style != "dome":
        return t
    extent = _field_radius(cfg)
    return t + cfg.badge.edge_size * max(0.0, 1 - (r / extent) ** 2)


def field_peak(cfg: BadgeConfig) -> float:
    return field_height(cfg, 0.0)


def _field_radius(cfg: BadgeConfig) -> float:
    return cfg.ring_inner_radius if cfg.ring.enabled else cfg.radius


def _top_profile(cfg: BadgeConfig) -> Profile:
    b = cfg.badge
    radius, rim = cfg.radius, cfg.rim_height
    if b.edge_style == "chamfer":
        shoulder = [(radius, rim - b.edge_size), (radius - b.edge_size, rim)]
    else:
        shoulder = [(radius, rim)]
    if cfg.ring.enabled:
        shoulder += ring.ring_inner_profile(cfg)
    if b.edge_style == "dome":
        extent = _field_radius(cfg)
        field = [(extent * (1 - k / DOME_STEPS), 0.0) for k in range(1, DOME_STEPS + 1)]
        field = [(r, field_height(cfg, r)) for r, _ in field]
    else:
        field = [(0.0, b.base_thickness)]
    return shoulder + field
