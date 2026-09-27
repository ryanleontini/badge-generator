"""Parametric car badge generator: Blender entry point.

Usage:
    blender -b -P badge_gen.py -- --config configs/front.toml

Exit codes: 0 success, 1 unexpected error, 2 invalid config.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from badge import booleans, compat, config, pipeline  # noqa: E402

log = logging.getLogger("badge")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="blender -b -P badge_gen.py --",
        description="Generate a 3D-printable circular badge from an SVG or text.",
    )
    parser.add_argument("--config", type=Path,
                        help="TOML config file (omit to build with built-in defaults)")
    parser.add_argument("--check", action="store_true",
                        help="validate the config and exit without building")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    # Blender passes its own arguments through sys.argv; ours follow "--".
    return parser.parse_args(argv[argv.index("--") + 1:] if "--" in argv else [])


def run(args: argparse.Namespace) -> int:
    start = time.perf_counter()
    compat.check_version()

    try:
        cfg = config.load_config(args.config, ROOT)
    except config.ConfigError as exc:
        log.error("invalid config:\n%s", exc)
        return 2
    log_summary(cfg)
    if args.check:
        log.info("config OK (--check, nothing built)")
        return 0

    log.info("boolean solver: %s", booleans.solver())
    try:
        build = pipeline.build_geometry(cfg)
    except booleans.NonManifoldError as exc:
        log.error("%s", exc)
        return 1
    pipeline.export_outputs(cfg, build)
    pipeline.log_report(build)

    log.info("done in %.2f s", time.perf_counter() - start)
    return 0


def log_summary(cfg: config.BadgeConfig) -> None:
    b = cfg.badge
    log.info("Blender %s | badge '%s' from %s", ".".join(map(str, compat.VERSION)), b.name,
             cfg.source.name if cfg.source else "defaults")
    log.info("disc: diameter %.2f mm, thickness %.2f mm, edge %s %.2f mm",
             b.diameter, b.base_thickness, b.edge_style, b.edge_size)
    if cfg.ring.enabled:
        log.info("ring: radius %.2f -> %.2f mm, height %.2f mm",
                 cfg.radius, cfg.ring_inner_radius, cfg.ring.height)
    source = cfg.emblem.text if cfg.emblem.mode == "text" else cfg.emblem.svg_path
    log.info("emblem: %s %r, fit radius %.2f mm, relief %.2f mm",
             cfg.emblem.mode, source, cfg.emblem_max_radius, cfg.emblem.relief)
    log.info("mounting: %s | output: %s", cfg.mounting.style, cfg.out_path)


def main() -> int:
    args = parse_args(sys.argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="[badge] %(levelname)s: %(message)s", stream=sys.stdout)
    try:
        return run(args)
    except Exception:
        log.exception("build failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
