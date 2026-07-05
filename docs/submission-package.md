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
- `base_edit.webm` (+ `base_edit.mp4` when ffmpeg is available)
- `final_episode.mp4` — the polished deliverable: retimed base edit with
  timed, speaker-colored captions burned in (built from the scene manifest;
  the sidecar `captions.ass` is kept for editing)
- `segments/*.webm` (+ `.mp4`)
- `hero_stills/*.png`
- `shorts/*.webm` (+ `.mp4`)
- `package_manifest.json`
- `index.html` review page

The raw WebM captures play in slow motion (MediaRecorder stamps frames in
wall-clock time while the capture loop advances the player by exactly 1/fps
per frame). When ffmpeg is found (`YVM_FFMPEG_PATH` or on `PATH`), packaging
automatically restamps every capture to normal speed as H.264 MP4s and points
the manifest and review page at them. To retime an existing package:

```bash
npm run retime:package -- --dir=output/submission/latest
```

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
