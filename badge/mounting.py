"""Mounting features on the flat back: adhesive-tape recess or locating pins.

The tape recess is a step in the base's lathe profile (manifold by
construction, no boolean). Pins are separate revolved solids unioned onto the
bottom face; their tips are chamfered so they start easily in their holes.
"""

import bpy

from .config import OVERLAP, BadgeConfig
from .mesh import Profile, revolve, to_object

PIN_SEGMENTS = 48


def bottom_profile(cfg: BadgeConfig) -> Profile | None:
    """Base bottom profile for the tape recess, or None for a plain flat bottom."""
    if cfg.mounting.style != "tape":
        return None
    depth = cfg.mounting.recess_depth
    recess_r = cfg.radius - cfg.mounting.recess_margin
    return [(0.0, depth), (recess_r, depth), (recess_r, 0.0), (cfg.radius, 0.0)]


def build_pins(cfg: BadgeConfig, collection: bpy.types.Collection) -> list[bpy.types.Object]:
    """Pins hanging below Z=0 at ``pin_positions``, overlapping OVERLAP into the base."""
    if cfg.mounting.style != "pins":
        return []
    m = cfg.mounting
    radius = m.pin_diameter / 2
    tip = min(0.5, radius / 2, m.pin_length / 4)
    profile = [(0.0, -m.pin_length), (radius - tip, -m.pin_length),
               (radius, -m.pin_length + tip), (radius, OVERLAP), (0.0, OVERLAP)]
    pins = []
    for i, (x, y) in enumerate(m.pin_positions):
        pin = to_object(revolve(profile, PIN_SEGMENTS), f"{cfg.badge.name}_pin{i}", collection)
        pin.location = (x, y, 0.0)
        pin.data.transform(pin.matrix_basis)  # bake the position into the mesh
        pin.location = (0.0, 0.0, 0.0)
        pins.append(pin)
    return pins
