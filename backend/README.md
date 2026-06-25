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
