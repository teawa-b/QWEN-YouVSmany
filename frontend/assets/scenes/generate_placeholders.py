"""Generate placeholder .glb studio sets for the premade-scene registry.

These are simple primitive-built sets (boxes/planes, flat PBR colors) — not
final art, but real, loadable glTF binaries so the Three.js player and the
full pipeline can be exercised end-to-end before a real artist/asset pass.
Geometry bounds match `backend/.../agents/scene_templates.py`: the open stage
area covers protagonist z=2.0 and the challenger arc x in [-1.6, 1.6] at
z=-0.5, with backdrop/seating placed further upstage (more negative z) and the
camera side toward positive z. Axes are Y-up, matching glTF/Three.js.

Run: python generate_placeholders.py
(requires `pip install trimesh numpy`; not a runtime dependency of the app)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh

OUT_DIR = Path(__file__).parent


def _box(extents, translate=(0, 0, 0), color=(200, 200, 200, 255)):
    m = trimesh.creation.box(extents=extents)
    m.apply_translation(translate)
    m.visual = trimesh.visual.ColorVisuals(m, face_colors=color)
    return m


def _arc_segments(n, radius, x_range, z_center, height, depth, color):
    """A handful of box segments swept along an arc — a cheap stand-in for a
    curved desk or seating riser."""
    lo, hi = x_range
    segs = []
    for i in range(n):
        t = i / max(1, n - 1)
        x = lo + (hi - lo) * t
        # Slight bow: pull the centre segments back so the arc reads as curved.
        bow = math.sin(t * math.pi) * 0.25
        seg = _box(
            (((hi - lo) / n) * 0.92, height, depth),
            translate=(x, height / 2, z_center - bow),
            color=color,
        )
        segs.append(seg)
    return segs


def _floor(color, z_range=(-3.0, 7.0), x_half=4.0):
    z_lo, z_hi = z_range
    return _box(
        (x_half * 2, 0.05, z_hi - z_lo),
        translate=(0, -0.025, (z_lo + z_hi) / 2),
        color=color,
    )


def studio_midnight() -> trimesh.Scene:
    """Dark blue broadcast studio, rim-lit semicircle desk."""
    scene = trimesh.Scene()
    scene.add_geometry(_floor((10, 16, 28, 255)))
    scene.add_geometry(_box((9, 3.2, 0.2), translate=(0, 1.6, -2.6), color=(15, 28, 48, 255)))
    # Semicircle desk hugging the challenger arc, just upstage of the marks.
    for seg in _arc_segments(5, 0.9, (-2.0, 2.0), z_center=-0.9, height=0.9, depth=0.5,
                              color=(24, 42, 70, 255)):
        scene.add_geometry(seg)
    # Thin emissive-looking rim strip along the top of the backdrop.
    scene.add_geometry(_box((9, 0.08, 0.05), translate=(0, 3.15, -2.5), color=(90, 140, 255, 255)))
    return scene


def amber_forum() -> trimesh.Scene:
    """Warm amber forum, tiered seating, central podium."""
    scene = trimesh.Scene()
    scene.add_geometry(_floor((59, 36, 18, 255)))
    # Two stepped seating risers behind the challenger arc.
    for i, (z, h) in enumerate([(-1.2, 0.35), (-2.0, 0.7)]):
        scene.add_geometry(
            _box((8 - i * 0.6, h, 0.6), translate=(0, h / 2, z), color=(120, 74, 28, 255))
        )
    # Central podium at the protagonist mark.
    scene.add_geometry(_box((0.7, 1.1, 0.7), translate=(0, 0.55, 2.0), color=(168, 102, 35, 255)))
    return scene


def clean_white() -> trimesh.Scene:
    """Minimal high-key white cyclorama — crisp silhouettes for image conversion."""
    scene = trimesh.Scene()
    scene.add_geometry(_floor((242, 242, 242, 255)))
    # A few curved-wall segments forming a soft cyclorama sweep.
    for seg in _arc_segments(7, 3.0, (-4.0, 4.0), z_center=-2.8, height=3.4, depth=0.15,
                              color=(248, 248, 248, 255)):
        scene.add_geometry(seg)
    return scene


SETS = {
    "studio_midnight": studio_midnight,
    "amber_forum": amber_forum,
    "clean_white": clean_white,
}


def main() -> None:
    for name, build in SETS.items():
        scene = build()
        out = OUT_DIR / f"{name}.glb"
        scene.export(file_obj=str(out), file_type="glb")
        print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
