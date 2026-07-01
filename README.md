# You Vs Many - AI Debate Showrunner

You Vs Many is a multi-agent debate pipeline for one-person-vs-many formats. The
current implementation is Phase 1: debate intelligence. It creates a cast,
private notes, a structured round plan, a locked transcript, scene cues,
highlight candidates, and metrics.

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
  --tags texture tradition culinary-innovation --seed 0
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

## Frontend

`frontend/index.html` is a static app. It can be opened directly or hosted by
any static host.

For local development with the backend on port 8000:

```bash
cd frontend
python -m http.server 5173
```

Open `http://127.0.0.1:5173`.

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
web API is pinned to mock right now, but the CLI/eval path can still use env
configuration:

```bash
cp backend/.env.example backend/.env
# YVM_PROVIDER=qwen
# QWEN_API_KEY=...
# QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# QWEN_TEXT_MODEL=qwen3.7-plus
```

For hosted browser playback, set the Qwen key on the backend service even when
`YVM_PROVIDER` stays `mock`. The API will keep deterministic mock debate text
but use Qwen Cloud CosyVoice for the scene audio timeline:

```text
QWEN_API_KEY=sk-...
YVM_TTS_PROVIDER=qwen
QWEN_TTS_MODEL=cosyvoice-v3-plus
QWEN_WS_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
```

Check `GET /health`; CosyVoice is available when it reports
`"tts_provider":"qwen"` and `"tts_ready":true`.

## Roadmap

Phase 2 audio/staging, Phase 3 still conversion, Phase 4 video transform,
Phase 5 continuity and shorts, then integration/eval. The locked transcript is
the artifact every downstream stage inherits.

## License

MIT - see `LICENSE`.
