# You Vs Many Backend

FastAPI API, debate agents, contracts, providers, CLI, evals, and tests.

## Run Locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn youvsmany.api.main:app --reload
```

The API defaults to `http://127.0.0.1:8000`.

## Test

```bash
pytest -q
```

## Main Endpoints

- `GET /health`
- `POST /episodes/run`
- `GET /episodes/{episode_id}/full`

The web API is currently pinned to the deterministic mock provider while the UI
is being refined.

## Railway

Create a Railway service from the repo with:

```text
Root Directory: /backend
Railway Config File: /backend/railway.toml
```

The start command is defined in `railway.toml` and binds Uvicorn to Railway's
`$PORT`.

For non-robotic hosted playback, configure Qwen Cloud CosyVoice on the backend
service:

```text
QWEN_API_KEY=sk-...
YVM_TTS_PROVIDER=qwen
QWEN_TTS_MODEL=cosyvoice-v3-plus
QWEN_WS_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
```

The web API can keep `YVM_PROVIDER=mock` for deterministic debate text. When a
Qwen key is present, scene staging uses CosyVoice clips and `/health` reports
`tts_provider: qwen` with `tts_ready: true`.
