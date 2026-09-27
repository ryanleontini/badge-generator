"""Raised outer ring, expressed as part of the base's lathe profile.

The ring is flush with the disc edge and shares the base's outer wall, so it is
not a separate solid: base.py splices this section into one revolve profile.
"""

from .config import BadgeConfig
from .mesh import Profile


def ring_inner_profile(cfg: BadgeConfig) -> Profile:
    """(r, z) points from the ring's top inner edge down to the base top face.

    The outer shoulder (chamfer or square edge) is handled by base.py.
    """
    top = cfg.rim_height
    inner = cfg.ring_inner_radius
    bevel = cfg.ring.inner_bevel
    return [(inner + bevel, top), (inner, top - bevel), (inner, cfg.badge.base_thickness)]
