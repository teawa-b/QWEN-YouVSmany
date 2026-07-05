"""Multi-model video variant generation for quality/lipsync comparison.

HappyHorse video-edit transfers motion from the silent 3D source clip, so the
mouth can never sync with the TTS line. DashScope offers audio-driven routes
(wan2.2-s2v speech-to-video, the wan2.5 i2v line with audio) where the voice
actually drives the lips. This module generates the *same* segment through
several candidate models so the routes can be compared side by side before
committing the episode pipeline to one.

Each variant is an async DashScope task (create -> poll -> download), with an
optional post-download audio mux for models that output silent video. Outputs
land in ``<video_out_dir>/variants/<label>.mp4`` (served by the existing
``/media/video-edit/files/`` mount) plus a variants manifest.

The request is constrained rather than a free proxy: task paths must be one of
the known aigc video paths and model names must match an explicit prefix
allowlist, mirroring the exposure level of the existing media endpoints.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from youvsmany.config import Settings
from youvsmany.media.video_edit import (
    download,
    ffmpeg_path,
    poll_task,
    public_url,
    video_out_dir,
)

# Known DashScope aigc video task paths (relative to the api/v1 base).
TASK_PATHS = {
    "video-generation": "/services/aigc/video-generation/video-synthesis",
    "image2video": "/services/aigc/image2video/video-synthesis",
}

ALLOWED_MODEL_PREFIXES = ("wan", "happyhorse", "emo", "videoretalk")

JOBS: dict[str, dict[str, Any]] = {}


def variants_dir(settings: Settings) -> Path:
    return video_out_dir(settings) / "variants"


def manifest_path(settings: Settings) -> Path:
    return variants_dir(settings) / "manifest.json"


def api_base(settings: Settings) -> str:
    # qwen_video_edit_url ends with a TASK_PATHS value; strip to the api base.
    url = settings.qwen_video_edit_url
    for path in TASK_PATHS.values():
        if url.endswith(path):
            return url[: -len(path)]
    return url.rsplit("/services/", 1)[0]


def validate_variant(variant: dict[str, Any]) -> str | None:
    if variant.get("path_key") not in TASK_PATHS:
        return f"path_key must be one of {sorted(TASK_PATHS)}"
    model = str(variant.get("model", ""))
    if not model.startswith(ALLOWED_MODEL_PREFIXES):
        return f"model must start with one of {ALLOWED_MODEL_PREFIXES}"
    if not isinstance(variant.get("input"), dict) or not variant["input"]:
        return "input must be a non-empty object"
    return None


def resolve_urls(base_url: str, value: Any) -> Any:
    """Rewrite site-relative media refs (e.g. '/audio/x.mp3') to public URLs."""
    if isinstance(value, str) and value.startswith("/"):
        return public_url(base_url, value)
    if isinstance(value, dict):
        return {k: resolve_urls(base_url, v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_urls(base_url, v) for v in value]
    return value


async def create_variant_task(
    client: httpx.AsyncClient, settings: Settings, variant: dict[str, Any]
) -> str:
    url = api_base(settings) + TASK_PATHS[variant["path_key"]]
    response = await client.post(
        url,
        headers={
            "Authorization": f"Bearer {settings.qwen_dashscope_api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        },
        json={
            "model": variant["model"],
            "input": variant["input"],
            "parameters": variant.get("parameters") or {},
        },
    )
    data = response.json() if response.content else {}
    task_id = data.get("output", {}).get("task_id")
    if response.status_code >= 400 or not task_id:
        raise RuntimeError(
            f"task create failed {response.status_code} "
            f"[{data.get('code', 'Unknown')}]: {data.get('message', data)}"
        )
    return task_id


def mux_audio(settings: Settings, video_file: Path, audio_url_or_file: str) -> None:
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return
    tmp = video_file.with_suffix(".mux.mp4")
    subprocess.run(
        [ffmpeg, "-y", "-i", str(video_file), "-i", audio_url_or_file,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest",
         str(tmp)],
        check=True, capture_output=True,
    )
    tmp.replace(video_file)


async def generate(
    settings: Settings,
    *,
    base_url: str,
    variants: list[dict[str, Any]],
    dry_run: bool = False,
    progress: Any | None = None,
) -> dict[str, Any]:
    if not dry_run and not settings.qwen_dashscope_api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY on the backend")

    out_dir = variants_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": dry_run,
        "variants": [],
    }
    results: dict[int, dict[str, Any]] = {}
    counters = {"done": 0, "failed": 0}

    def flush() -> None:
        manifest["variants"] = [results[i] for i in sorted(results)]
        manifest["generated_count"] = sum(
            1 for v in manifest["variants"] if v.get("status") == "generated"
        )
        manifest["failed_count"] = sum(
            1 for v in manifest["variants"] if v.get("status") == "failed"
        )
        manifest_path(settings).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    async def run_variant(client: httpx.AsyncClient, index: int, variant: dict[str, Any]) -> None:
        label = str(variant.get("label") or f"variant_{index:02d}")
        entry: dict[str, Any] = {
            "label": label,
            "model": variant["model"],
            "path_key": variant["path_key"],
        }
        try:
            resolved = {
                **variant,
                "input": resolve_urls(base_url, variant["input"]),
                "parameters": resolve_urls(base_url, variant.get("parameters") or {}),
            }
            entry["request"] = {"input": resolved["input"], "parameters": resolved["parameters"]}
            if dry_run:
                entry["status"] = "planned"
            else:
                task_id = await create_variant_task(client, settings, resolved)
                entry["task_id"] = task_id
                result = await poll_task(client, settings, task_id)
                video_url = result.get("output", {}).get("video_url") or result.get(
                    "output", {}
                ).get("results", {}).get("video_url")
                if not video_url:
                    raise RuntimeError(f"no video_url in finished task: {result}")
                video_rel = f"variants/{label}.mp4"
                await download(client, video_url, video_out_dir(settings) / video_rel)
                if variant.get("mux_audio"):
                    mux_audio(
                        settings,
                        video_out_dir(settings) / video_rel,
                        resolve_urls(base_url, variant["mux_audio"]),
                    )
                entry["video"] = video_rel
                entry["status"] = "generated"
        except Exception as exc:
            counters["failed"] += 1
            entry["status"] = "failed"
            entry["error"] = str(exc)
        finally:
            counters["done"] += 1
            results[index] = entry
            if progress:
                progress({
                    "current": counters["done"], "total": len(variants),
                    "path": entry.get("video") or label, "failed": counters["failed"],
                })
            flush()

    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        await asyncio.gather(*(run_variant(client, i, v) for i, v in enumerate(variants)))

    flush()
    return manifest


def create_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id, "status": "queued", "current": 0, "total": 0,
        "path": None, "failed": 0, "error": None, "manifest": None,
        "created_at": time.time(), "updated_at": time.time(),
    }
    JOBS[job_id] = job
    return job


async def run_job(job_id: str, settings: Settings, **kwargs: Any) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    job["updated_at"] = time.time()

    def progress(update: dict[str, Any]) -> None:
        job.update(update)
        job["updated_at"] = time.time()

    try:
        manifest = await generate(settings, progress=progress, **kwargs)
        variants = manifest.get("variants", [])
        generated = [v for v in variants if v.get("status") in {"generated", "planned"}]
        failures = [v for v in variants if v.get("status") == "failed"]
        job["failed"] = len(failures)
        job["status"] = (
            "failed" if failures and not generated else "partial" if failures else "succeeded"
        )
        if failures:
            job["error"] = failures[0].get("error")
        job["manifest"] = {
            "variants": len(variants),
            "generated": len(generated),
            "failed": len(failures),
            "files_url": "/media/video-edit/files/variants/",
        }
    except Exception as exc:  # pragma: no cover - defensive job reporting
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
