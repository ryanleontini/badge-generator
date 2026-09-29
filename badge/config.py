"""Load, default and validate badge configuration from TOML.

This module is pure Python (no ``bpy``) so it can be unit-tested outside
Blender. All dimensions are millimeters.

Relative paths inside a config (``svg_path``, ``font_path``, ``out_dir``)
are resolved against the project root, not the config file's directory, so
configs read naturally: ``svg_path = "art/front.svg"``.
"""

import dataclasses
import difflib
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Geometric constants shared by the geometry modules.
OVERLAP = 0.05  # how far unioned parts sink into the base for clean booleans
MIN_EMBLEM_RADIUS = 2.0  # smallest usable emblem area before we call it an error
RING_FUSE = 0.3  # with margin = 0, how far the emblem sinks into the ring so they fuse
MIN_GAP = 0.2  # smallest emblem-to-ring gap that still prints as a real gap

EDGE_STYLES = ("flat", "chamfer", "dome")
EMBLEM_MODES = ("svg", "text")
RING_PARTS = ("base", "emblem")
MOUNTING_STYLES = ("tape", "pins", "none")
NAME_RE = re.compile(r"[A-Za-z0-9_-]+")

PinList = list[tuple[float, float]]


class ConfigError(Exception):
    """One or more problems with a config. ``errors`` holds every message."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(f"  - {e}" for e in errors))


@dataclass
class BadgeSection:
    name: str = "badge"
    diameter: float = 75.0
    base_thickness: float = 3.0
    edge_style: str = "chamfer"
    edge_size: float = 0.8
    segments: int = 256


@dataclass
class RingSection:
    enabled: bool = True
    width: float = 4.0
    height: float = 1.2
    inner_bevel: float = 0.4
    part: str = "base"  # which printed part (and color) the ring belongs to


@dataclass
class EmblemSection:
    mode: str = "text"
    svg_path: str = ""
    text: str = "RB"
    font_path: str = ""
    relief: float = 1.2
    margin: float = 3.0
    rotation_deg: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass
class MountingSection:
    style: str = "tape"
    recess_depth: float = 0.6
    recess_margin: float = 2.0
    pin_diameter: float = 3.0
    pin_length: float = 6.0
    pin_positions: PinList = field(default_factory=lambda: [(-20.0, 0.0), (20.0, 0.0)])


@dataclass
class ExportSection:
    split_bodies: bool = True
    single_body: bool = True
    render_preview: bool = True
    out_dir: str = "out"


SECTIONS = {
    "badge": BadgeSection,
    "ring": RingSection,
    "emblem": EmblemSection,
    "mounting": MountingSection,
    "export": ExportSection,
}


@dataclass
class BadgeConfig:
    badge: BadgeSection
    ring: RingSection
    emblem: EmblemSection
    mounting: MountingSection
    export: ExportSection
    root: Path
    source: Path | None = None

    @property
    def radius(self) -> float:
        return self.badge.diameter / 2

    @property
    def ring_inner_radius(self) -> float:
        # The ring is flush with the disc edge; the edge bevel runs up to its top.
        return self.radius - self.ring.width

    @property
    def rim_height(self) -> float:
        """Height of the outer wall + edge bevel: the ring top if enabled, else the base top."""
        return self.badge.base_thickness + (self.ring.height if self.ring.enabled else 0.0)

    @property
    def emblem_area_radius(self) -> float:
        """Radius of the region the emblem may occupy, before margin/offset."""
        if self.ring.enabled:
            return self.ring_inner_radius
        if self.badge.edge_style == "chamfer":
            return self.radius - self.badge.edge_size
        return self.radius

    @property
    def emblem_touches_ring(self) -> bool:
        return self.ring.enabled and self.emblem.margin == 0

    @property
    def emblem_max_radius(self) -> float:
        """Radius of the emblem's enclosing circle, about its offset center.

        With margin = 0 the emblem reaches RING_FUSE into the ring so the two fuse
        into one solid instead of meeting along a zero-width seam.
        """
        offset = math.hypot(self.emblem.offset_x, self.emblem.offset_y)
        fuse = RING_FUSE if self.emblem_touches_ring else 0.0
        return self.emblem_area_radius - self.emblem.margin - offset + fuse

    @property
    def svg_file(self) -> Path:
        return self._resolve(self.emblem.svg_path)

    @property
    def font_file(self) -> Path | None:
        return self._resolve(self.emblem.font_path) if self.emblem.font_path else None

    @property
    def out_path(self) -> Path:
        return self._resolve(self.export.out_dir)

    def _resolve(self, p: str) -> Path:
        path = Path(p).expanduser()
        return path if path.is_absolute() else self.root / path


def load_config(path: Path | None, root: Path) -> BadgeConfig:
    """Load a TOML config (or pure defaults when ``path`` is None) and validate it."""
    if path is None:
        return from_dict({}, root)
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ConfigError([f"config file not found: {path}"])
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([f"{path.name}: invalid TOML: {exc}"]) from None
    return from_dict(data, root, source=path)


def from_dict(data: dict[str, Any], root: Path, source: Path | None = None) -> BadgeConfig:
    """Build a config from parsed TOML, applying defaults. Raises ConfigError."""
    errors: list[str] = []
    for key in data:
        if key not in SECTIONS:
            errors.append(_unknown(f"[{key}]", key, SECTIONS))
    sections = {
        name: _build_section(cls, data.get(name, {}), name, errors)
        for name, cls in SECTIONS.items()
    }
    cfg = BadgeConfig(**sections, root=root, source=source)
    errors.extend(validate(cfg))
    if errors:
        raise ConfigError(errors)
    return cfg


def validate(cfg: BadgeConfig) -> list[str]:
    """Return every problem with ``cfg``; an empty list means it is buildable."""
    errors: list[str] = []

    def require(ok: bool, msg: str) -> None:
        if not ok:
            errors.append(msg)

    b, r, em, m, x = cfg.badge, cfg.ring, cfg.emblem, cfg.mounting, cfg.export

    # [badge]
    require(bool(NAME_RE.fullmatch(b.name)),
            f"badge.name {b.name!r} may only contain letters, digits, '-' and '_'")
    require(b.diameter > 0, "badge.diameter must be > 0")
    require(b.base_thickness > 0, "badge.base_thickness must be > 0")
    require(b.edge_style in EDGE_STYLES,
            f"badge.edge_style must be one of {EDGE_STYLES}, got {b.edge_style!r}")
    require(16 <= b.segments <= 4096, "badge.segments must be between 16 and 4096")
    if b.edge_style == "chamfer":
        require(0 < b.edge_size < cfg.rim_height,
                f"badge.edge_size ({b.edge_size}) must be > 0 and < the rim height "
                f"({cfg.rim_height:.2f} mm) for a chamfer")
    elif b.edge_style == "dome":
        require(b.edge_size > 0, "badge.edge_size (dome rise) must be > 0")
    if b.edge_style != "flat":
        require(b.edge_size < cfg.radius, "badge.edge_size must be smaller than the disc radius")

    # [ring]
    if r.enabled:
        require(r.width > 0, "ring.width must be > 0")
        require(r.height > 0, "ring.height must be > 0")
        require(cfg.ring_inner_radius > 0,
                f"ring.width ({r.width}) leaves no inner opening on a "
                f"{b.diameter} mm badge")
        require(0 <= r.inner_bevel < min(r.width, r.height),
                "ring.inner_bevel must be >= 0 and smaller than ring width and height")
        require(r.part in RING_PARTS,
                f"ring.part must be one of {RING_PARTS}, got {r.part!r}")
        if r.part == "emblem" and b.edge_style == "chamfer":
            require(b.edge_size < r.height,
                    f"badge.edge_size ({b.edge_size}) must be < ring.height ({r.height}) when "
                    f"ring.part = 'emblem', so the chamfer stays on the ring")
        if b.edge_style == "chamfer":
            require(b.edge_size + r.inner_bevel < r.width,
                    f"badge.edge_size + ring.inner_bevel ({b.edge_size + r.inner_bevel:.2f}) "
                    f"must be < ring.width ({r.width}) to leave a flat ring top")

    # [emblem]
    require(em.mode in EMBLEM_MODES,
            f"emblem.mode must be one of {EMBLEM_MODES}, got {em.mode!r}")
    require(em.relief > 0, "emblem.relief must be > 0")
    require(em.margin == 0 or em.margin >= MIN_GAP,
            f"emblem.margin must be 0 (touch the ring) or >= {MIN_GAP} mm (a printable gap), "
            f"got {em.margin}")
    if em.mode == "svg":
        if not em.svg_path:
            errors.append("emblem.svg_path is required when emblem.mode = 'svg'")
        elif not cfg.svg_file.is_file():
            errors.append(f"emblem.svg_path not found: {cfg.svg_file}")
    elif em.mode == "text":
        require(bool(em.text.strip()), "emblem.text must not be empty when emblem.mode = 'text'")
    if em.font_path and not cfg.font_file.is_file():
        errors.append(f"emblem.font_path not found: {cfg.font_file}")
    bound = "ring inner edge" if r.enabled else "top face edge"
    require(cfg.emblem_max_radius >= MIN_EMBLEM_RADIUS,
            f"emblem does not fit: {bound} radius {cfg.emblem_area_radius:.2f} mm "
            f"- margin {em.margin:.2f} - offset "
            f"{math.hypot(em.offset_x, em.offset_y):.2f} leaves "
            f"{cfg.emblem_max_radius:.2f} mm (need >= {MIN_EMBLEM_RADIUS} mm)")

    # [mounting]
    require(m.style in MOUNTING_STYLES,
            f"mounting.style must be one of {MOUNTING_STYLES}, got {m.style!r}")
    if m.style == "tape":
        require(0 < m.recess_depth < b.base_thickness,
                f"mounting.recess_depth ({m.recess_depth}) must be > 0 and < "
                f"base_thickness ({b.base_thickness})")
        require(0 <= m.recess_margin < cfg.radius,
                "mounting.recess_margin must be >= 0 and smaller than the disc radius")
    elif m.style == "pins":
        require(m.pin_diameter > 0, "mounting.pin_diameter must be > 0")
        require(m.pin_length > 0, "mounting.pin_length must be > 0")
        require(len(m.pin_positions) > 0, "mounting.pin_positions must list at least one pin")
        for i, (px, py) in enumerate(m.pin_positions):
            reach = math.hypot(px, py) + m.pin_diameter / 2
            require(reach <= cfg.radius,
                    f"mounting.pin_positions[{i}] ({px}, {py}) puts the pin outside the "
                    f"disc (reaches {reach:.2f} mm, radius {cfg.radius:.2f} mm)")

    # [export]
    require(x.split_bodies or x.single_body,
            "export: at least one of split_bodies / single_body must be true")
    require(bool(x.out_dir), "export.out_dir must not be empty")

    return errors


def _build_section(cls: type, table: Any, section: str, errors: list[str]) -> Any:
    if not isinstance(table, dict):
        errors.append(f"[{section}] must be a table")
        return cls()
    fields = {f.name: f for f in dataclasses.fields(cls)}
    values = {}
    for key, raw in table.items():
        where = f"{section}.{key}"
        if key not in fields:
            errors.append(_unknown(where, key, fields))
            continue
        try:
            values[key] = _coerce(raw, fields[key].type, where)
        except ValueError as exc:
            errors.append(str(exc))
    return cls(**values)


_TYPE_NAMES = {float: "a number", int: "an integer", bool: "true or false", str: "a string"}


def _coerce(raw: Any, expected: Any, where: str) -> Any:
    if expected is float and isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if not math.isfinite(raw):
            raise ValueError(f"{where}: must be a finite number, got {raw!r}")
        return float(raw)
    if expected in (int, bool, str) and type(raw) is expected:
        return raw
    if expected == PinList:
        return _coerce_points(raw, where)
    raise ValueError(f"{where}: expected {_TYPE_NAMES.get(expected, expected)}, got {raw!r}")


def _coerce_points(raw: Any, where: str) -> PinList:
    msg = f"{where}: expected a list of [x, y] pairs, got {raw!r}"
    if not isinstance(raw, list):
        raise ValueError(msg)
    points = []
    for item in raw:
        if not (isinstance(item, list) and len(item) == 2):
            raise ValueError(msg)
        points.append(tuple(_coerce(v, float, where) for v in item))
    return points


def _unknown(where: str, key: str, allowed: Any) -> str:
    hint = difflib.get_close_matches(key, list(allowed), n=1)
    suffix = f" (did you mean {hint[0]!r}?)" if hint else ""
    return f"unknown key {where}{suffix}"
