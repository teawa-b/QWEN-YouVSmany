# Premade studio sets (glTF / GLB)

These are the debate-studio environments the Three.js player loads at runtime.
The backend never builds a stage procedurally — the Stage Director picks one of
these sets (see `backend/.../agents/scene_templates.py`) and the manifest
references its `asset_url` here.

| template_id      | file                   | look |
|------------------|------------------------|------|
| `studio_midnight`| `studio_midnight.glb`  | dark blue broadcast studio, rim-lit semicircle desk |
| `amber_forum`    | `amber_forum.glb`      | warm amber forum, tiered seating, central podium |
| `clean_white`    | `clean_white.glb`      | minimal high-key white cyclorama (best for image conversion) |

## Current status: placeholder geometry, real assets

`generate_placeholders.py` builds simple primitive versions of all three sets
(flat-colored floor + backdrop + desk/seating/podium boxes, sized to the stage
bounds in `scene_templates.py`). These are real, loadable `.glb` binaries — not
final art — so the Three.js player and the full pipeline can be exercised
end-to-end today. Regenerate with:

```
pip install trimesh numpy scipy
python generate_placeholders.py
```

## Replacing with final art

When real sets are ready (hand-authored, licensed, or AI-generated), just drop
matching-named `.glb` files in this directory — no registry or code changes
needed, since the Stage Director only ever references `asset_url` by name.

- Keep a clear, uncluttered stage area; avoid baked-in text/logos (they mutate
  during the Phase 3 image conversion).
- Leave the central stage area open so character marks fit a 1–5 person cast
  symmetrically (the marks are placed by the Stage Director, not baked into the set).
- High-contrast key/fill/rim lighting for clean silhouettes.
- Compose so the action reads inside both a 16:9 frame and a centred 9:16 crop.
