"""Blender version detection. API differences between versions are branched here."""

import bpy

MIN_VERSION = (4, 2, 0)
VERSION: tuple[int, int, int] = tuple(bpy.app.version)


def check_version() -> None:
    if VERSION < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        raise RuntimeError(f"Blender {need}+ required, running {bpy.app.version_string}")
