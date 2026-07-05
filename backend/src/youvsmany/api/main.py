"""FastAPI orchestrator for debate episodes and media generation.

Implements the episode endpoints:
  POST /episodes              create brief + run safety gate
  POST /episodes/{id}/prepare generate cast, private notes, round plan
  POST /episodes/{id}/debate  run/advance the state machine
  POST /episodes/{id}/lock    detect highlights, approve
  GET  /episodes/{id}         current status, summary and outputs

Also exposes realistic-reference and HappyHorse video-edit media endpoints.
"""

from __future__ import annotations

import asyncio
import os
from importlib.util import find_spec

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from youvsmany.adapters.mock_provider import MockProvider
from youvsmany.adapters.factory import effective_tts_provider
from youvsmany.agents import orchestrator
from youvsmany.agents.orchestrator import SafetyRejected
from youvsmany.config import get_settings
from youvsmany.contracts.brief import ShowBrief
from youvsmany.evals.metrics import score_episode
from youvsmany.media import characters, reference_assets, video_edit
from youvsmany.store import EpisodeStore

app = FastAPI(title="You Vs Many — Debate Intelligence", version="0.1.0")

# The frontend is hosted separately, so allow browser clients from other origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve rendered CosyVoice clips (referenced by scene manifest audio cues) so the
# browser can stream them; harmless when TTS is mock (the folder stays empty).
_audio_dir = get_settings().audio_dir
os.makedirs(_audio_dir, exist_ok=True)
app.mount("/audio", StaticFiles(directory=_audio_dir), name="audio")

_settings = get_settings()
reference_assets.ensure_realistic_bank(_settings)
_realistic_ref_dir = _settings.realistic_ref_dir
os.makedirs(_realistic_ref_dir, exist_ok=True)
app.mount(
    "/media/realistic-refs/files",
    StaticFiles(directory=_realistic_ref_dir),
    name="realistic-refs",
)

# Persistent reusable character identity bank (generated once, reused per run).
characters.ensure_character_bank(_settings)
_character_bank_dir = _settings.character_bank_dir
os.makedirs(_character_bank_dir, exist_ok=True)
app.mount(
    "/media/character-bank/files",
    StaticFiles(directory=_character_bank_dir),
    name="character-bank",
)

# HappyHorse video edit needs DashScope-fetchable public URLs for the starter
# frames, their MP4 conversions, and hosts the generated segment videos.
_source_ref_dir = reference_assets.source_ref_dir()
if _source_ref_dir.exists():
    app.mount(
        "/media/reference/files",
        StaticFiles(directory=str(_source_ref_dir)),
        name="reference-source",
    )
_reference_mp4_dir = get_settings().reference_mp4_dir
os.makedirs(_reference_mp4_dir, exist_ok=True)
app.mount(
    "/media/reference-mp4/files",
    StaticFiles(directory=_reference_mp4_dir),
    name="reference-mp4",
)
_video_out_dir = get_settings().video_out_dir
os.makedirs(_video_out_dir, exist_ok=True)
app.mount(
    "/media/video-edit/files",
    StaticFiles(directory=_video_out_dir),
    name="video-edit",
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
                "visual_presentation": c.visual_presentation,
                "contention_tag": c.contention_tag,
                "core_contention": c.core_contention,
            }
            for c in (ep.cast.all_speakers() if ep.cast else [])
        ],
        "turns": [t.model_dump() for t in ep.transcript.turns],
        "duration_s": ep.transcript.total_duration_s,
        "highlights": [h.model_dump() for h in ep.highlights],
        "scene": ep.scene_manifest.model_dump() if ep.scene_manifest else None,
        "metrics": score_episode(ep).model_dump() if ep.transcript.turns else None,
        "run_report": ep.run_report.model_dump(),
    }


class PrepareBody(BaseModel):
    suggested_tags: list[str] | None = None


class RunBody(BaseModel):
    brief: ShowBrief
    suggested_tags: list[str] | None = None


class VideoEditSegment(BaseModel):
    segment_id: str
    speaker_id: str | None = None
    prompt: str
    clip: str = Field(description="Starter clip path relative to the reference bank")
    identity: str | None = Field(default=None, description="Identity starter frame path")
    starter: str | None = Field(default=None, description="Pose starter frame path")
    audio: str | None = Field(default=None, description="TTS clip URL to mux, if any")
    character: str | None = Field(
        default=None,
        description="Persistent roster character id whose bank identity image anchors the face",
    )
    dialogue: str | None = Field(
        default=None, description="Spoken line, burned as a caption into the stitched video"
    )
    speaker_name: str | None = Field(default=None, description="Caption speaker label")
    speaker_color: str | None = Field(
        default=None, description="Caption speaker color (hex, e.g. #7b97ff)"
    )


class VideoEditGenerateBody(BaseModel):
    segments: list[VideoEditSegment] = Field(min_length=1)
    resolution: str = "720P"
    dry_run: bool = False
    stitch: bool = True
    background: bool = True
    limit: int = Field(default=0, ge=0, description="0 generates every segment")


class RealisticRefsGenerateBody(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=0, ge=0, description="0 generates the whole bank")
    overwrite: bool = False
    # Small pacing delay; rate limits are handled by retry/backoff per shot.
    delay_ms: int = Field(default=2000, ge=0, le=120000)
    background: bool = True
    size: str = "1080*1920"


@app.get("/")
def index() -> dict:
    return {"status": "ok", "service": "youvsmany-api", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    provider = _provider()
    tts_provider = effective_tts_provider(settings)
    tts_ready = (
        tts_provider == "qwen"
        and bool(settings.qwen_api_key)
        and find_spec("dashscope") is not None
    )
    return {
        "status": "ok",
        "provider": provider.name,
        "model": provider.model,
        "tts_provider": tts_provider,
        "tts_configured": settings.tts_provider,
        "tts_model": settings.qwen_tts_model if tts_provider == "qwen" else "mock-tts-1",
        "tts_ready": tts_ready,
        "media_endpoints": True,
        "image_model": settings.qwen_image_edit_model,
        "image_ready": bool(settings.qwen_dashscope_api_key),
        "video_model": settings.qwen_video_edit_model,
        "video_ready": bool(settings.qwen_dashscope_api_key),
        "ffmpeg": bool(video_edit.ffmpeg_path()),
    }


@app.get("/media/realistic-refs/status")
def realistic_refs_status() -> dict:
    try:
        return reference_assets.status(get_settings())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"reference source missing: {exc}") from exc


@app.get("/media/realistic-refs/manifest.json")
def realistic_refs_manifest():
    file = reference_assets.manifest_path(get_settings())
    if not file.exists():
        raise HTTPException(status_code=404, detail="realistic reference manifest not generated")
    return FileResponse(file, media_type="application/json")


@app.post("/media/realistic-refs/generate")
async def generate_realistic_refs(body: RealisticRefsGenerateBody) -> dict:
    settings = get_settings()
    if not body.dry_run and not settings.qwen_dashscope_api_key:
        raise HTTPException(
            status_code=503,
            detail="Qwen/DashScope key is not configured on this backend",
        )

    kwargs = {
        "dry_run": body.dry_run,
        "limit": body.limit,
        "overwrite": body.overwrite,
        "delay_ms": body.delay_ms,
        "size": body.size,
    }
    if body.background:
        job = reference_assets.create_job()
        asyncio.create_task(reference_assets.run_job(job["job_id"], settings, **kwargs))
        return {"status": "queued", "job": job}

    try:
        manifest = await reference_assets.generate(settings, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "succeeded",
        "shots": len(manifest.get("shots", [])),
        "manifest_url": "/media/realistic-refs/manifest.json",
        "files_url": "/media/realistic-refs/files/",
    }


@app.get("/media/realistic-refs/jobs/{job_id}")
def realistic_refs_job(job_id: str) -> dict:
    job = reference_assets.JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


class CharacterBankGenerateBody(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=0, ge=0, description="0 generates the whole roster")
    overwrite: bool = False
    background: bool = True
    size: str = "1080*1920"


@app.get("/media/character-bank/status")
def character_bank_status() -> dict:
    return characters.status(get_settings())


@app.get("/media/character-bank/manifest.json")
def character_bank_manifest():
    file = characters.manifest_path(get_settings())
    if not file.exists():
        raise HTTPException(status_code=404, detail="character bank manifest not generated")
    return FileResponse(file, media_type="application/json")


@app.post("/media/character-bank/generate")
async def generate_character_bank(body: CharacterBankGenerateBody) -> dict:
    settings = get_settings()
    if not body.dry_run and not settings.qwen_dashscope_api_key:
        raise HTTPException(
            status_code=503,
            detail="Qwen/DashScope key is not configured on this backend",
        )

    kwargs = {
        "dry_run": body.dry_run,
        "limit": body.limit,
        "overwrite": body.overwrite,
        "size": body.size,
    }
    if body.background:
        job = characters.create_job()
        asyncio.create_task(characters.run_job(job["job_id"], settings, **kwargs))
        return {"status": "queued", "job": job}

    try:
        manifest = await characters.generate(settings, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "succeeded",
        "characters": len(manifest.get("characters", [])),
        "manifest_url": "/media/character-bank/manifest.json",
        "files_url": "/media/character-bank/files/",
    }


@app.get("/media/character-bank/jobs/{job_id}")
def character_bank_job(job_id: str) -> dict:
    job = characters.JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/media/video-edit/status")
def video_edit_status() -> dict:
    return video_edit.status(get_settings())


@app.get("/media/video-edit/manifest.json")
def video_edit_manifest():
    file = video_edit.video_out_dir(get_settings()) / "manifest.json"
    if not file.exists():
        raise HTTPException(status_code=404, detail="video manifest not generated")
    return FileResponse(file, media_type="application/json")


@app.post("/media/video-edit/generate")
async def generate_video_edit(body: VideoEditGenerateBody, request: Request) -> dict:
    settings = get_settings()
    if not body.dry_run and not settings.qwen_dashscope_api_key:
        raise HTTPException(
            status_code=503,
            detail="Qwen/DashScope key is not configured on this backend",
        )
    base_url = settings.public_base_url or str(request.base_url).rstrip("/")
    # Railway terminates TLS at the proxy; DashScope must fetch over https.
    if base_url.startswith("http://") and "localhost" not in base_url and "127.0.0.1" not in base_url:
        base_url = "https://" + base_url[len("http://"):]
    segments = [s.model_dump() for s in body.segments]
    if body.limit:
        segments = segments[: body.limit]

    kwargs = {
        "base_url": base_url,
        "segments": segments,
        "resolution": body.resolution,
        "dry_run": body.dry_run,
        "stitch_output": body.stitch,
    }
    if body.background:
        job = video_edit.create_job()
        asyncio.create_task(video_edit.run_job(job["job_id"], settings, **kwargs))
        return {"status": "queued", "job": job}

    try:
        manifest = await video_edit.generate(settings, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "succeeded",
        "segments": len(manifest.get("segments", [])),
        "conversation": manifest.get("conversation"),
        "manifest_url": "/media/video-edit/manifest.json",
        "files_url": "/media/video-edit/files/",
    }


@app.get("/media/video-edit/jobs/{job_id}")
def video_edit_job(job_id: str) -> dict:
    job = video_edit.VIDEO_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


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
