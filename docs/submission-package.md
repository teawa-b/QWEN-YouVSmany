# Submission Package Workflow

`npm run package:episode` creates the handoff bundle for a finished You Vs Many
episode. It uses the running backend for the locked episode, then drives the
Three.js player in Playwright to capture the visual deliverables.

```bash
cd frontend
npm run package:episode -- \
  --url=http://127.0.0.1:5173 \
  --api=http://127.0.0.1:8000 \
  --out=output/submission/latest
```

The package contains:

- `episode.json` and `scene_manifest.json`
- `metrics.json`
- `base_edit.webm`
- `segments/*.webm`
- `hero_stills/*.png`
- `shorts/*.webm`
- `package_manifest.json`
- `index.html` review page

For a quick smoke test, cap the render:

```bash
npm run package:episode -- \
  --url=http://127.0.0.1:5173 \
  --api=http://127.0.0.1:8000 \
  --out=output/submission/smoke \
  --limit=3 \
  --duration-scale=0.15 \
  --segment-cap-ms=700 \
  --stills=3
```

The script keeps output paths inside the repo and writes under `output/` by
default, so generated deliverables stay out of git.
