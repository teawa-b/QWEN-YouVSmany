# You Vs Many - AI Debate Showrunner

You Vs Many is a short-form AI showrunner. A creator supplies one debatable
claim; the agent writes a seven-beat script, casts one lead and two challengers,
storyboards the scene, generates voices, directs the visual pass, and assembles
one vertical episode. Every layer enforces the product contract: the finished
video can never run longer than 30 seconds.

The current implementation is a complete vertical slice built for the AI
Showrunner track: multi-agent debate intelligence, an audio-locked Three.js
previsualization player, Qwen Cloud CosyVoice support, a persisted realistic
character bank, live HappyHorse video-edit endpoints, download-ready final
cuts, and a submission packaging workflow.

The repo is split so the API and UI can be hosted separately:

```text
backend/
  src/youvsmany/   FastAPI app, agents, contracts, providers, CLI, store
  tests/           pytest suite
  data/            starter topic prompts
  evals/           rubric docs
  samples/         example locked episode manifests
  pyproject.toml   backend package config

frontend/
  index.html       static single-page app
```

## Backend

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

# API
uvicorn youvsmany.api.main:app --reload

# Tests
pytest -q

# CLI debate run
python -m youvsmany.cli --topic "Pineapple belongs on pizza" \
  --tags texture tradition --seed 0
```

On Windows PowerShell, using the existing root virtualenv also works:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

The API is currently pinned to the deterministic mock provider for UI testing.
It exposes:

- `GET /health`
- `POST /episodes/run`
- `POST /episodes`
- `POST /episodes/{id}/prepare`
- `POST /episodes/{id}/debate`
- `POST /episodes/{id}/lock`
- `GET /episodes/{id}`
- `GET /episodes/{id}/full`
- `GET /media/realistic-refs/status`
- `POST /media/realistic-refs/generate`
- `GET /media/character-bank/status`
- `POST /media/character-bank/generate`
- `GET /media/video-edit/status`
- `POST /media/video-edit/generate`
- `GET /media/shorts/status`
- `POST /media/shorts/generate`
- `POST /media/video-variants/generate`

## Frontend

`frontend/index.html` is a static app. The Node server in `frontend/server.js`
serves the app and media assets with the MIME types needed for WebM/MP4/GLB
playback.

For local development with the backend on port 8000:

```bash
cd frontend
npm start
```

Open `http://127.0.0.1:5173`.

The creator UI intentionally exposes one constrained format rather than a
technical dashboard: 1 lead + 2 challengers, 7 directed beats, vertical 9:16,
and a hard 30-second maximum. Preview, final render, playback, and MP4 download
live in the same final-cut workspace.

To create a reviewable deliverable bundle from a running backend/frontend:

```bash
cd frontend
npm run package:episode -- --url=http://127.0.0.1:5173 --api=http://127.0.0.1:8000
```

The package writes episode JSON, scene manifests, base edit, per-segment clips,
hero stills, short candidates, and a review page under `output/submission/`.

For separate hosting, point the frontend at the backend API with one of:

```text
https://your-frontend.example.com/?api=https://your-api.example.com
```

```js
window.YVM_API_BASE = "https://your-api.example.com";
```

```js
localStorage.setItem("YVM_API_BASE", "https://your-api.example.com");
```

The backend has permissive CORS enabled for now so the separately hosted
frontend can call it.

## Railway Hosting

This repo is ready for two Railway services from the same GitHub repo:

```text
backend service
  Root Directory: /backend
  Railway Config File: /backend/railway.toml

frontend service
  Root Directory: /frontend
  Railway Config File: /frontend/railway.toml
```

After Railway gives the backend service a public domain, set this on the
frontend service:

```text
YVM_API_BASE=https://your-backend-domain.up.railway.app
```

The frontend runtime server emits `config.js`, which sets `window.YVM_API_BASE`
from that variable. The browser then calls the hosted backend for `/health` and
`/episodes/run`.

## Provider Setup

The backend supports live Qwen or offline mock through the provider layer. The
web API, CLI and eval path all honor the same environment configuration:

```bash
cp backend/.env.example backend/.env
YVM_PROVIDER=qwen
# QWEN_API_KEY=...
# QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# QWEN_TEXT_MODEL=qwen3.7-plus
```

For the full hosted showrunner, enable Qwen for both the agent pipeline and the
CosyVoice scene audio timeline:

```text
QWEN_API_KEY=sk-...
YVM_PROVIDER=qwen
YVM_TTS_PROVIDER=qwen
QWEN_TTS_MODEL=cosyvoice-v3-plus
QWEN_WS_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
```

Check `GET /health`; CosyVoice is available when it reports
`"tts_provider":"qwen"` and `"tts_ready":true`.

## Consistency & the Character Roster

Two mechanisms keep generated media coherent:

- **One canonical studio room.** Every image-edit and video-edit prompt embeds
  the same studio description (`backend/src/youvsmany/media/studio.py`,
  mirrored as `STUDIO_SCENE` in `frontend/index.html`; a test enforces the
  sync), so all characters and shots land in the same room.
- **A persistent character roster.** `CHARACTER_ROSTER` defines 12 varied
  reusable panelists with stable seeds. The stage director deterministically
  casts them onto each episode's speakers (`scene.character_refs`), and their
  identity images are generated **once** into
  `frontend/assets/reference/characters-v1/` via
  `POST /media/character-bank/generate` (then persisted with
  `npm run pull:character-bank`). Episodes reuse the saved identities instead
  of generating new characters every run — faster and consistent.

## Status

The app has the full brief -> script -> cast -> storyboard -> voice ->
HappyHorse render -> final edit/download path. The July 2026 product pass also
replaced the generic dashboard with a creator-first showrunner experience and
made the 30-second rule structural across schemas, dialogue, scene timing,
render requests, and FFmpeg output.

## License

MIT - see `LICENSE`.
