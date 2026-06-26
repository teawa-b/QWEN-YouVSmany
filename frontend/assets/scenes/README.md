# Premade studio sets (glTF / GLB)

These are the art-directed debate-studio environments the Three.js player loads at
runtime. The backend never builds a stage procedurally — the Stage Director picks
one of these sets (see `backend/.../agents/scene_templates.py`) and the manifest
references its `asset_url` here.

Expected files (one `.glb` per registry template):

| template_id      | file                   | look |
|------------------|------------------------|------|
| `studio_midnight`| `studio_midnight.glb`  | dark blue broadcast studio, rim-lit semicircle desk |
| `amber_forum`    | `amber_forum.glb`      | warm amber forum, tiered seating, central podium |
| `clean_white`    | `clean_white.glb`      | minimal high-key white cyclorama (best for image conversion) |

## Authoring guidance

- Keep a clear, uncluttered stage area; avoid baked-in text/logos (they mutate
  during the Phase 3 image conversion).
- Leave the central stage area open so character marks fit a 1–5 person cast
  symmetrically (the marks are placed by the Stage Director, not baked into the set).
- High-contrast key/fill/rim lighting for clean silhouettes.
- Compose so the action reads inside both a 16:9 frame and a centred 9:16 crop.

> Placeholder: drop the real `.glb` files here. Until then the manifest still
> references them so the contract and UI can be developed against mock runs.
