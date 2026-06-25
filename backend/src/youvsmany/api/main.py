"""FastAPI orchestrator — Phase 1 subset of the API surface (blueprint Appendix A).

Implements the text-stage endpoints:
  POST /episodes              create brief + run safety gate
  POST /episodes/{id}/prepare generate cast, private notes, round plan
  POST /episodes/{id}/debate  run/advance the state machine
  POST /episodes/{id}/lock    detect highlights, approve
  GET  /episodes/{id}         current status, summary and outputs

Media endpoints (captures/images/videos/package) belong to later phases.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from youvsmany.adapters.mock_provider import MockProvider
from youvsmany.agents import orchestrator
from youvsmany.agents.orchestrator import SafetyRejected
from youvsmany.config import get_settings
from youvsmany.contracts.brief import ShowBrief
from youvsmany.evals.metrics import score_episode
from youvsmany.store import EpisodeStore

app = FastAPI(title="You Vs Many — Debate Intelligence", version="0.1.0")

# The frontend is hosted separately, so allow browser clients from other origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _store() -> EpisodeStore:
    return EpisodeStore(get_settings().run_dir)


def _provider() -> MockProvider:
    """Pin the web app to deterministic mock generation while the UI is refined."""
    return MockProvider()


def _episode_view(ep) -> dict:
    """Full client-facing episode payload: cast, transcript turns, highlights,
    metrics and run report — everything the frontend needs to render a debate."""
    return {
        "episode_id": ep.episode_id,
        "version": ep.version,
        "state": ep.state,
        "approved": ep.approved,
        "topic": ep.brief.topic,
        "protagonist_position": ep.brief.protagonist_position,
        "safety": ep.safety.model_dump() if ep.safety else None,
        "cast": [
            {
                "character_id": c.character_id,
                "display_name": c.display_name,
                "role": c.role,
                "stance": c.stance,
                "contention_tag": c.contention_tag,
                "core_contention": c.core_contention,
            }
            for c in (ep.cast.all_speakers() if ep.cast else [])
        ],
        "turns": [t.model_dump() for t in ep.transcript.turns],
        "duration_s": ep.transcript.total_duration_s,
        "highlights": [h.model_dump() for h in ep.highlights],
        "metrics": score_episode(ep).model_dump() if ep.transcript.turns else None,
        "run_report": ep.run_report.model_dump(),
    }


class PrepareBody(BaseModel):
    suggested_tags: list[str] | None = None


class RunBody(BaseModel):
    brief: ShowBrief
    suggested_tags: list[str] | None = None


@app.get("/")
def index() -> dict:
    return {"status": "ok", "service": "youvsmany-api", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict:
    provider = _provider()
    return {"status": "ok", "provider": provider.name, "model": provider.model}


@app.post("/episodes/run")
def run_episode(body: RunBody) -> dict:
    """One-shot: brief -> prepare -> debate -> lock, returning the full episode."""
    provider = _provider()
    try:
        ep = orchestrator.run_full(
            body.brief, provider=provider, suggested_tags=body.suggested_tags
        )
    except SafetyRejected as e:
        raise HTTPException(status_code=422, detail=f"safety: {e}")
    _store().save(ep)
    return _episode_view(ep)


@app.post("/episodes")
def create_episode(brief: ShowBrief) -> dict:
    provider = _provider()
    try:
        ep = orchestrator.create_episode(brief, provider=provider)
    except SafetyRejected as e:
        raise HTTPException(status_code=422, detail=f"safety: {e}")
    _store().save(ep)
    return {"episode_id": ep.episode_id, "state": ep.state, "safety": ep.safety.model_dump()}


@app.post("/episodes/{episode_id}/prepare")
def prepare(episode_id: str, body: PrepareBody | None = None) -> dict:
    store = _store()
    ep = _load(store, episode_id)
    provider = _provider()
    orchestrator.prepare_episode(
        ep, provider=provider, suggested_tags=(body.suggested_tags if body else None)
    )
    store.save(ep)
    return {
        "episode_id": ep.episode_id,
        "state": ep.state,
        "cast": [c.display_name for c in ep.cast.all_speakers()],
        "contention_tags": [c.contention_tag for c in ep.cast.challengers],
    }


@app.post("/episodes/{episode_id}/debate")
def debate(episode_id: str) -> dict:
    store = _store()
    ep = _load(store, episode_id)
    orchestrator.run_debate(ep, provider=_provider())
    store.save(ep)
    return {"episode_id": ep.episode_id, "state": ep.state, "turns": len(ep.transcript.turns)}


@app.post("/episodes/{episode_id}/lock")
def lock(episode_id: str) -> dict:
    store = _store()
    ep = _load(store, episode_id)
    orchestrator.lock_episode(ep)
    store.save(ep)
    return {
        "episode_id": ep.episode_id,
        "state": ep.state,
        "approved": ep.approved,
        "duration_s": ep.transcript.total_duration_s,
        "highlights": len(ep.highlights),
    }


@app.get("/episodes/{episode_id}")
def get_episode(episode_id: str) -> dict:
    ep = _load(_store(), episode_id)
    return {
        "episode_id": ep.episode_id,
        "version": ep.version,
        "state": ep.state,
        "approved": ep.approved,
        "topic": ep.brief.topic,
        "turns": len(ep.transcript.turns),
        "duration_s": ep.transcript.total_duration_s,
        "highlights": [h.model_dump() for h in ep.highlights],
        "run_report": ep.run_report.model_dump(),
    }


@app.get("/episodes/{episode_id}/full")
def get_episode_full(episode_id: str) -> dict:
    return _episode_view(_load(_store(), episode_id))


def _load(store: EpisodeStore, episode_id: str):
    if not store.exists(episode_id):
        raise HTTPException(status_code=404, detail="episode not found")
    return store.load_latest(episode_id)
