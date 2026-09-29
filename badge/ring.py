"""Raised outer ring.

By default (``ring.part = "base"``) the ring is part of the base's lathe profile:
flush with the disc edge and sharing its outer wall, so base + ring is one
solid with no booleans. With ``ring.part = "emblem"`` the ring is built as its
own solid sitting on the base top face, so it prints with the emblem (e.g. a
chrome ring and logo on a body-color disc).
"""

import bpy

from .config import BadgeConfig
from .mesh import Profile, revolve, to_object


def ring_inner_profile(cfg: BadgeConfig) -> Profile:
    """(r, z) points from the ring's top inner edge down to the base top face.

    The outer shoulder (chamfer or square edge) is handled by the caller.
    """
    top = cfg.rim_height
    inner = cfg.ring_inner_radius
    bevel = cfg.ring.inner_bevel
    return [(inner + bevel, top), (inner, top - bevel), (inner, cfg.badge.base_thickness)]


def outer_shoulder(cfg: BadgeConfig) -> Profile:
    """(r, z) points up the outer wall to the rim top, including the chamfer."""
    radius, rim, edge = cfg.radius, cfg.rim_height, cfg.badge.edge_size
    if cfg.badge.edge_style == "chamfer":
        return [(radius, rim - edge), (radius - edge, rim)]
    return [(radius, rim)]


def build_ring(cfg: BadgeConfig, collection: bpy.types.Collection) -> bpy.types.Object:
    """The ring as a standalone solid from the base top face (z = base_thickness) up."""
    bottom = cfg.badge.base_thickness
    profile = ([(cfg.ring_inner_radius, bottom), (cfg.radius, bottom)]
               + outer_shoulder(cfg) + ring_inner_profile(cfg)[:-1])
    return to_object(revolve(profile, cfg.badge.segments, closed=True),
                     f"{cfg.badge.name}_ring", collection)
