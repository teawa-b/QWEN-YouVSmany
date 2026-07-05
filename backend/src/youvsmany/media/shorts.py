"""Realistic highlight shorts: the cost-aware wan2.6 route.

Full-episode realistic generation is billed per second and structurally too
expensive per episode. The show's shareable artifact is the highlight short,
so this module renders **only the hero segments** (the clip curator's short
candidates) through an audio-driven Wan i2v model at 720P:

- each hero segment = the speaker's persistent roster identity image + their
  CosyVoice line -> one lipsynced clip (duration billed at 5s or 10s, chosen
  from the line length);
- segments are hard-capped (``YVM_SHORT_SEGMENT_CAP``, default 3) so one
  request can never burn more than a few generated clips;
- finished clips are normalized, concatenated with their native audio, and
  the timed speaker captions are burned in — same styling as the episode.

Output lands in ``<video_out_dir>/shorts/short.mp4`` (served by the existing
``/media/video-edit/files/`` mount) plus a manifest for the UI.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from youvsmany.config import Settings
from youvsmany.media import characters
from youvsmany.media.studio import STUDIO_SCENE
from youvsmany.media.video_edit import (
    build_captions_ass,
    download,
    ffmpeg_path,
    media_duration_s,
    poll_task,
    public_url,
    video_out_dir,
)
from youvsmany.media.video_variants import ALLOWED_MODEL_PREFIXES, create_variant_task

DEFAULT_MODEL = "wan2.6-i2v"
DEFAULT_RESOLUTION = "720P"

# Hard spend cap: a single short request never generates more clips than this.
def segment_cap() -> int:
    return max(1, int(os.getenv("YVM_SHORT_SEGMENT_CAP", "3")))


JOBS: dict[str, dict[str, Any]] = {}


def shorts_dir(settings: Settings) -> Path:
    return video_out_dir(settings) / "shorts"


def manifest_path(settings: Settings) -> Path:
    return shorts_dir(settings) / "manifest.json"


def status(settings: Settings) -> dict[str, Any]:
    manifest = None
    file = manifest_path(settings)
    if file.exists():
        manifest = json.loads(file.read_text(encoding="utf-8"))
    return {
        "video_ready": bool(settings.qwen_dashscope_api_key),
        "ffmpeg": bool(ffmpeg_path()),
        "model": DEFAULT_MODEL,
        "resolution": DEFAULT_RESOLUTION,
        "segment_cap": segment_cap(),
        "short": (manifest or {}).get("short"),
        "files_url": "/media/video-edit/files/",
        "manifest_url": "/media/shorts/manifest.json" if manifest else None,
    }


def billed_duration_s(line_duration_s: float) -> int:
    """Wan i2v bills 5s or 10s clips; short lines fit the cheaper tier."""
    return 5 if line_duration_s <= 4.5 else 10


def prompt_for(description: str) -> str:
    subject = description or "the debate-show panelist from the reference image"
    return " ".join(
        [
            f"Subject: {subject}, seated at the debate desk, speaking directly to camera",
            "with natural hand gestures, lips synchronized to the audio.",
            f"Scene: {STUDIO_SCENE}.",
            "Camera: static medium close-up, vertical 9:16 framing.",
            "Style: photorealistic broadcast footage, natural lighting, gentle depth of field.",
            "No captions, no lower thirds, no text, no logos, no watermark.",
        ]
    )


def resolve_identity_url(
    base_url: str, roster_id: str | None, character_manifest: dict[str, Any] | None
) -> str | None:
    for entry in (character_manifest or {}).get("characters", []):
        if entry.get("roster_id") == roster_id and entry.get("status") in {"generated", "existing"}:
            return public_url(base_url, f"/media/character-bank/files/{entry['identity']}")
    return None


def stitch_short(settings: Settings, entries: list[dict[str, Any]], out_dir: Path) -> str | None:
    """Normalize the generated clips (keeping their native lipsynced audio),
    concatenate, and burn the timed speaker captions."""
    ffmpeg = ffmpeg_path()
    videos = [e for e in entries if e.get("status") == "generated" and e.get("video")]
    if not ffmpeg or not videos:
        return None
    work = out_dir / "stitch"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    for i, entry in enumerate(videos):
        part = work / f"part_{i:03d}.mp4"
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(out_dir / entry["video"]),
                "-vf", "scale=720:1280,setsar=1", "-r", "30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                str(part),
            ],
            check=True, capture_output=True,
        )
        parts.append(part)
        duration = media_duration_s(part)
        if duration:
            cues.append(
                {
                    "start_s": cursor,
                    "end_s": cursor + duration,
                    "dialogue": entry.get("dialogue"),
                    "speaker_name": entry.get("speaker_name"),
                    "speaker_color": entry.get("speaker_color"),
                }
            )
            cursor += duration
    list_file = work / "concat.txt"
    list_file.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    raw = work / "short_raw.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(raw)],
        check=True, capture_output=True,
    )

    output = out_dir / "short.mp4"
    if any(c.get("dialogue") for c in cues):
        ass_file = out_dir / "short_captions.ass"
        ass_file.write_text(build_captions_ass(cues), encoding="utf-8")
        ass_arg = str(ass_file).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        subprocess.run(
            [ffmpeg, "-y", "-i", str(raw), "-vf", f"subtitles='{ass_arg}'",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
             "-movflags", "+faststart", str(output)],
            check=True, capture_output=True,
        )
    else:
        shutil.move(str(raw), str(output))
    shutil.rmtree(work, ignore_errors=True)
    return "shorts/short.mp4"


async def generate(
    settings: Settings,
    *,
    base_url: str,
    segments: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    resolution: str = DEFAULT_RESOLUTION,
    dry_run: bool = False,
    progress: Any | None = None,
) -> dict[str, Any]:
    if not model.startswith(ALLOWED_MODEL_PREFIXES):
        raise ValueError(f"model must start with one of {ALLOWED_MODEL_PREFIXES}")
    if not dry_run and not settings.qwen_dashscope_api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY on the backend")
    if not dry_run and not ffmpeg_path():
        raise RuntimeError("ffmpeg is not installed on this backend")

    out_dir = shorts_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    character_manifest = characters.existing_manifest(settings)
    capped = segments[: segment_cap()]

    manifest: dict[str, Any] = {
        "version": 1,
        "model": model,
        "resolution": resolution,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": dry_run,
        "requested_segments": len(segments),
        "segment_cap": segment_cap(),
        "segments": [],
        "short": None,
    }
    results: dict[int, dict[str, Any]] = {}
    counters = {"done": 0, "failed": 0}

    def flush() -> None:
        manifest["segments"] = [results[i] for i in sorted(results)]
        manifest["generated_count"] = sum(
            1 for s in manifest["segments"] if s.get("status") == "generated"
        )
        manifest["failed_count"] = sum(
            1 for s in manifest["segments"] if s.get("status") == "failed"
        )
        manifest_path(settings).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    async def run_segment(client: httpx.AsyncClient, index: int, segment: dict[str, Any]) -> None:
        entry: dict[str, Any] = {
            "index": index,
            "segment_id": segment.get("segment_id", f"segment_{index:03d}"),
            "character": segment.get("character"),
            "dialogue": segment.get("dialogue"),
            "speaker_name": segment.get("speaker_name"),
            "speaker_color": segment.get("speaker_color"),
        }
        try:
            identity_url = resolve_identity_url(base_url, segment.get("character"), character_manifest)
            if not identity_url:
                raise RuntimeError(
                    f"no generated identity for roster character {segment.get('character')!r} "
                    "(run /media/character-bank/generate first)"
                )
            if not segment.get("audio"):
                raise RuntimeError("segment has no TTS audio ref")
            duration = billed_duration_s(float(segment.get("duration_s") or 10))
            description = ""
            for roster_entry in (character_manifest or {}).get("characters", []):
                if roster_entry.get("roster_id") == segment.get("character"):
                    description = roster_entry.get("description", "")
                    break
            variant = {
                "label": entry["segment_id"],
                "model": model,
                "path_key": "video-generation",
                "input": {
                    "img_url": identity_url,
                    "audio_url": public_url(base_url, segment["audio"]),
                    "prompt": prompt_for(description),
                },
                "parameters": {"resolution": resolution, "duration": duration},
            }
            entry["billed_duration_s"] = duration
            entry["prompt"] = variant["input"]["prompt"]
            if dry_run:
                entry["status"] = "planned"
            else:
                task_id = await create_variant_task(client, settings, variant)
                entry["task_id"] = task_id
                result = await poll_task(client, settings, task_id)
                video_url = result.get("output", {}).get("video_url")
                if not video_url:
                    raise RuntimeError(f"no video_url in finished task: {result}")
                video_rel = f"segments/{index:03d}_{entry['segment_id']}.mp4"
                await download(client, video_url, out_dir / video_rel)
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
                    "current": counters["done"], "total": len(capped),
                    "path": entry.get("video") or entry["segment_id"],
                    "failed": counters["failed"],
                })
            flush()

    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        await asyncio.gather(*(run_segment(client, i, s) for i, s in enumerate(capped)))

    if not dry_run:
        try:
            manifest["short"] = stitch_short(settings, manifest["segments"], out_dir)
        except subprocess.CalledProcessError as exc:
            manifest["stitch_error"] = (exc.stderr or b"").decode("utf-8", "replace")[-2000:]
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
        segments = manifest.get("segments", [])
        generated = [s for s in segments if s.get("status") in {"generated", "planned"}]
        failures = [s for s in segments if s.get("status") == "failed"]
        job["failed"] = len(failures)
        job["status"] = (
            "failed" if failures and not generated else "partial" if failures else "succeeded"
        )
        if failures:
            job["error"] = failures[0].get("error")
        job["manifest"] = {
            "segments": len(segments),
            "generated": len(generated),
            "failed": len(failures),
            "short": manifest.get("short"),
            "files_url": "/media/video-edit/files/",
        }
    except Exception as exc:  # pragma: no cover - defensive job reporting
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
