"""Independent binary-STL inspection (pure Python, no Blender).

Checks the files a slicer will actually see: size, triangle count, and
watertightness (every edge shared by exactly two triangles, consistently
oriented) and outward normals (positive signed volume).

    python3 tests/stl_check.py out/front_full.stl
    blender -b -P tests/stl_check.py -- out/*.stl
"""

import struct
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StlInfo:
    triangles: int
    min: tuple[float, float, float]
    max: tuple[float, float, float]
    open_edges: int  # edges not shared by exactly two triangles
    flipped_edges: int  # shared edges traversed the same direction twice
    volume: float  # signed, mm^3; negative means inside-out normals

    @property
    def size(self) -> tuple[float, ...]:
        return tuple(b - a for a, b in zip(self.min, self.max))

    @property
    def watertight(self) -> bool:
        return self.open_edges == 0 and self.flipped_edges == 0 and self.volume > 0


def read_stl(path: Path, precision: int = 5) -> StlInfo:
    data = Path(path).read_bytes()
    (count,) = struct.unpack_from("<I", data, 80)
    if len(data) != 84 + 50 * count:
        raise ValueError(f"{path}: not a binary STL (size mismatch)")
    directed: Counter = Counter()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    volume = 0.0
    for i in range(count):
        vals = struct.unpack_from("<12f", data, 84 + 50 * i)
        verts = [tuple(round(c, precision) for c in vals[3 + 3 * k: 6 + 3 * k]) for k in range(3)]
        for v in verts:
            for axis in range(3):
                lo[axis] = min(lo[axis], v[axis])
                hi[axis] = max(hi[axis], v[axis])
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = verts
        volume += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx)
                   + az * (bx * cy - by * cx)) / 6
        for k in range(3):
            directed[(verts[k], verts[(k + 1) % 3])] += 1
    undirected: Counter = Counter()
    for (a, b), n in directed.items():
        undirected[frozenset((a, b))] += n
    open_edges = sum(1 for n in undirected.values() if n != 2)
    flipped = sum(1 for (a, b), n in directed.items() if n > 1 or (b, a) not in directed)
    return StlInfo(count, tuple(lo), tuple(hi), open_edges, flipped, volume)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ok = True
    for arg in args:
        info = read_stl(Path(arg))
        ok &= info.watertight
        print(f"{arg}: {info.triangles} tris, size "
              f"{' x '.join(f'{s:.3f}' for s in info.size)} mm, {info.volume / 1000:.2f} cm3, "
              f"{'watertight' if info.watertight else 'NOT watertight'} "
              f"(open {info.open_edges}, flipped {info.flipped_edges})")
    sys.exit(0 if ok else 1)
