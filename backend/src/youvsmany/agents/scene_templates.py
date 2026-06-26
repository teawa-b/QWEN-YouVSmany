"""Registry of premade studio sets (blueprint 5.3, premade-scene approach).

Rather than build a stage procedurally in Three.js at runtime, the stage director
picks one of these art-directed sets. Each is a glTF/GLB asset the player loads;
the cast is then placed on marks fit *inside* the set's stage bounds (so N
challengers stay symmetric), and the predefined camera anchors are reused.

The `.glb` assets live in the frontend (frontend/assets/scenes/); the backend
only needs their ids, capacities, stage bounds and camera anchors to stage and
validate an episode offline.
"""

from __future__ import annotations

import hashlib

from youvsmany.contracts.scene import CameraAnchor, CameraShot, SceneTemplate, Vec3


def _hash_float(parts: str) -> float:
    h = hashlib.sha256(parts.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _studio_anchors() -> list[CameraAnchor]:
    """The standard six-camera coverage every set ships (blueprint 5.3).

    `protagonist_close` looks at the sentinel "protagonist", which the stage
    director rewrites to the bound protagonist id once the cast is placed."""
    return [
        CameraAnchor(name="wide_master", shot=CameraShot.WIDE_MASTER,
                     position=Vec3(x=0.0, y=1.6, z=6.0), look_at="stage_center"),
        CameraAnchor(name="protagonist_close", shot=CameraShot.PROTAGONIST_CLOSE,
                     position=Vec3(x=0.0, y=1.6, z=3.6), look_at="protagonist"),
        CameraAnchor(name="reaction", shot=CameraShot.REACTION,
                     position=Vec3(x=1.0, y=1.9, z=4.5), look_at="stage_center"),
        CameraAnchor(name="two_shot", shot=CameraShot.TWO_SHOT,
                     position=Vec3(x=0.8, y=1.6, z=4.2), look_at="stage_center"),
    ]


# A small library is enough — the blueprint only ever describes one studio look.
TEMPLATES: list[SceneTemplate] = [
    SceneTemplate(
        template_id="studio_midnight",
        display_name="Midnight Debate Studio",
        asset_url="/assets/scenes/studio_midnight.glb",
        environment="dark blue broadcast studio, rim-lit semicircle desk, soft floor glow",
        max_challengers=5,
        base_anchors=_studio_anchors(),
    ),
    SceneTemplate(
        template_id="amber_forum",
        display_name="Amber Forum",
        asset_url="/assets/scenes/amber_forum.glb",
        environment="warm amber forum with tiered seating and a central podium",
        max_challengers=5,
        base_anchors=_studio_anchors(),
    ),
    SceneTemplate(
        template_id="clean_white",
        display_name="Clean White Stage",
        asset_url="/assets/scenes/clean_white.glb",
        environment="minimal high-key white cyclorama, crisp silhouettes for image conversion",
        max_challengers=5,
        base_anchors=_studio_anchors(),
    ),
]

_BY_ID = {t.template_id: t for t in TEMPLATES}


def get_template(template_id: str) -> SceneTemplate:
    return _BY_ID[template_id]


def select_template(num_challengers: int, seed: int) -> SceneTemplate:
    """Deterministically pick a set that can seat the cast (blueprint: reproducible
    from the manifest). Falls back to the highest-capacity set if none fit."""
    eligible = [t for t in TEMPLATES if t.max_challengers >= num_challengers]
    if not eligible:
        return max(TEMPLATES, key=lambda t: t.max_challengers)
    idx = int(_hash_float(f"template{seed}:{num_challengers}") * len(eligible)) % len(eligible)
    return eligible[idx]
