"""Qwen-backed HappyHorse video-edit generation.

Turns per-segment source motion clips (the silent 9:16 starter WebM captures)
into realistic live-action video segments with ``happyhorse-1.0-video-edit``,
then stitches the finished segments into one full conversation video.

The DashScope video API is asynchronous (create task -> poll) and only accepts
public media URLs for the source video, so the backend:

1. serves the starter bank at ``/media/reference/files/`` and converts each
   WebM clip to MP4 (HappyHorse accepts MP4/MOV only) with ffmpeg, served at
   ``/media/reference-mp4/files/``;
2. sends each segment as its own task (identity reference image is the
   generated realistic close shot when the realistic bank exists, otherwise
   the starter frame) and polls them with bounded concurrency;
3. downloads finished segment videos into a served media directory and, when
   ffmpeg is available, concatenates them (muxing per-segment TTS audio when
   an ``audio`` URL is provided) into ``conversation.mp4``.

Failures follow the realistic-refs conventions: one failed segment records a
failed entry and the run continues; the job manifest is rewritten after every
segment so partial results are visible while the job runs.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from youvsmany.config import Settings
from youvsmany.contracts.transcript import MAX_EPISODE_DURATION_S
from youvsmany.media.reference_assets import (
    QwenRequestError,
    RETRYABLE_CODES,
    ensure_realistic_bank,
    repo_root,
    source_ref_dir,
)

VIDEO_JOBS: dict[str, dict[str, Any]] = {}

# DashScope guidance: video tasks take 1-5 minutes; poll roughly every 15s.
POLL_INTERVAL_S = 15
POLL_TIMEOUT_S = 15 * 60
MAX_CONCURRENT_TASKS = 2
# HappyHorse requires a source video of at least 3s; the starter capture clips
# are ~2s, so each is looped up to this target duration during MP4 conversion.
MIN_CLIP_S = 4.0
MAX_EPISODE_SEGMENTS = 7


def video_out_dir(settings: Settings) -> Path:
    return Path(settings.video_out_dir)


def mp4_cache_dir(settings: Settings) -> Path:
    return Path(settings.reference_mp4_dir)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def status(settings: Settings) -> dict[str, Any]:
    out = video_out_dir(settings)
    manifest_file = out / "manifest.json"
    manifest = None
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    return {
        "video_ready": bool(settings.qwen_dashscope_api_key),
        "ffmpeg": bool(ffmpeg_path()),
        "model": settings.qwen_video_edit_model,
        "manifest_url": "/media/video-edit/manifest.json" if manifest else None,
        "files_url": "/media/video-edit/files/",
        "segments": len(manifest.get("segments", [])) if manifest else 0,
        "conversation": manifest.get("conversation") if manifest else None,
        "max_duration_s": MAX_EPISODE_DURATION_S,
    }


def ensure_mp4(settings: Settings, clip_rel: str) -> Path:
    """Convert a starter WebM clip to MP4 once; HappyHorse rejects WebM."""
    source = source_ref_dir() / clip_rel
    if not source.exists():
        raise FileNotFoundError(f"source clip missing: {clip_rel}")
    target = mp4_cache_dir(settings) / Path(clip_rel).with_suffix(".mp4")
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed on this backend")
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            # Loop the short source and trim to a fixed target so the clip clears
            # HappyHorse's 3s minimum while staying well under its 15s cap.
            "-stream_loop",
            "-1",
            "-i",
            str(source),
            "-t",
            str(MIN_CLIP_S),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


def public_url(base: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return base.rstrip("/") + "/" + path.lstrip("/")


def build_media(
    settings: Settings,
    base_url: str,
    segment: dict[str, Any],
    realistic_manifest: dict[str, Any] | None,
    character_manifest: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Media list for one HappyHorse task: source MP4 + identity reference(s).

    Identity resolution order (first reference image wins the face):
    1. the segment's persistent roster character (``character`` = roster_id)
       from the pre-generated character bank — reused across episodes;
    2. the generated realistic close shot for the slot starter;
    3. the raw starter frame.
    The slot starter (realistic or raw) stays in the list as the pose anchor.
    """
    ensure_mp4(settings, segment["clip"])
    mp4_rel = str(Path(segment["clip"]).with_suffix(".mp4")).replace("\\", "/")
    media = [{"type": "video", "url": public_url(base_url, f"/media/reference-mp4/files/{mp4_rel}")}]

    def character_identity_for(roster_id: str | None) -> str | None:
        if not roster_id:
            return None
        for entry in (character_manifest or {}).get("characters", []):
            if entry.get("roster_id") == roster_id and entry.get("status") in {
                "generated",
                "existing",
            }:
                return entry.get("identity")
        return None

    def realistic_for(starter_rel: str) -> str | None:
        for shot in (realistic_manifest or {}).get("shots", []):
            if shot.get("starter") == starter_rel and shot.get("status") in {"generated", "existing"}:
                return shot.get("realistic")
        return None

    character_identity = character_identity_for(segment.get("character"))
    if character_identity:
        media.append(
            {
                "type": "reference_image",
                "url": public_url(base_url, f"/media/character-bank/files/{character_identity}"),
            }
        )

    identity_rel = None if character_identity else (segment.get("identity") or segment.get("starter"))
    for ref_rel in dict.fromkeys(filter(None, [identity_rel, segment.get("starter")])):
        realistic = realistic_for(ref_rel)
        url = (
            public_url(base_url, f"/media/realistic-refs/files/{realistic}")
            if realistic
            else public_url(base_url, f"/media/reference/files/{ref_rel}")
        )
        media.append({"type": "reference_image", "url": url})
    return media[:5]


async def create_task(
    client: httpx.AsyncClient,
    settings: Settings,
    media: list[dict[str, str]],
    prompt: str,
    resolution: str,
) -> str:
    response = await client.post(
        settings.qwen_video_edit_url,
        headers={
            "Authorization": f"Bearer {settings.qwen_dashscope_api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        },
        json={
            "model": settings.qwen_video_edit_model,
            "input": {"prompt": prompt, "media": media},
            "parameters": {"resolution": resolution, "watermark": False},
        },
    )
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code >= 400:
        raise QwenRequestError(
            response.status_code,
            str(data.get("code", "Unknown")),
            str(data.get("message", data or response.text)),
        )
    task_id = data.get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"No task_id in response: {data}")
    return task_id


async def create_task_with_retry(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    media: list[dict[str, str]],
    prompt: str,
    resolution: str,
    max_attempts: int = 5,
) -> str:
    attempt = 0
    while True:
        attempt += 1
        try:
            return await create_task(client, settings, media, prompt, resolution)
        except QwenRequestError as exc:
            if not exc.retryable or attempt >= max_attempts:
                raise
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= max_attempts:
                raise
        await asyncio.sleep(min(2**attempt * 2, 45))


async def poll_task(client: httpx.AsyncClient, settings: Settings, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        response = await client.get(
            f"{settings.qwen_task_url_base.rstrip('/')}/{task_id}",
            headers={"Authorization": f"Bearer {settings.qwen_dashscope_api_key}"},
        )
        data = response.json()
        task_status = data.get("output", {}).get("task_status", "")
        if task_status == "SUCCEEDED":
            return data
        if task_status in {"FAILED", "CANCELED", "UNKNOWN"}:
            output = data.get("output", {})
            raise RuntimeError(
                f"video task {task_status} [{output.get('code', '?')}]: {output.get('message', '')}"
            )
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"video task {task_id} did not finish within {POLL_TIMEOUT_S}s")


async def download(client: httpx.AsyncClient, url: str, file: Path) -> None:
    response = await client.get(url)
    response.raise_for_status()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(response.content)


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def media_duration_s(file: Path) -> float | None:
    ffprobe = ffprobe_path()
    if not ffprobe:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(file)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _ass_time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


def _ass_color(hex_color: str) -> str:
    hex_color = (hex_color or "#ffffff").lstrip("#")
    if len(hex_color) != 6:
        hex_color = "ffffff"
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H{(b + g + r).upper()}&"


def _ass_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_captions_ass(cues: list[dict[str, Any]]) -> str:
    """Styled ASS captions for the stitched conversation. ``cues`` items carry
    start_s/end_s/dialogue plus optional speaker_name/speaker_color (hex).
    Mirrors the caption styling in frontend/scripts/finalize_episode.mjs,
    scaled for the 1080x1920 stitch output."""
    events = []
    for cue in cues:
        if not cue.get("dialogue"):
            continue
        name = _ass_escape(str(cue.get("speaker_name") or "").upper())
        color = _ass_color(cue.get("speaker_color") or "#ffffff")
        text = _ass_escape(cue["dialogue"])
        lead = f"{{\\c{color}}}{name}\\N" if name else ""
        events.append(
            f"Dialogue: 0,{_ass_time(cue['start_s'])},{_ass_time(cue['end_s'])},Caption,,0,0,0,,"
            f"{lead}{{\\c&HFFFFFF&}}{text}"
        )
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 0",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Caption,DejaVu Sans,44,&HFFFFFF&,&HFFFFFF&,&H90101318&,&H90101318&,-1,0,0,0,100,100,0,0,3,20,0,2,56,56,128,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )


def stitch(settings: Settings, entries: list[dict[str, Any]], out_dir: Path) -> str | None:
    """Concatenate finished segment videos (muxing per-segment TTS audio when
    given) into conversation.mp4, burning timed speaker captions when the
    segments carry dialogue. Returns the relative output path, or None."""
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
        remaining = MAX_EPISODE_DURATION_S - cursor
        if remaining <= 0:
            break
        segment_file = out_dir / entry["video"]
        part = work / f"part_{i:03d}.mp4"
        cmd = [ffmpeg, "-y", "-i", str(segment_file)]
        audio_file = out_dir / entry["audio_file"] if entry.get("audio_file") else None
        if audio_file and audio_file.exists():
            cmd += ["-i", str(audio_file), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-shortest"]
        else:
            cmd += ["-an"]
        requested = float(entry.get("duration_s") or remaining)
        part_cap = max(0.1, min(requested, remaining))
        # Normalise every part so concat never mixes stream parameters. The
        # per-part trim plus the final trim makes the 30s ceiling impossible to
        # bypass even when upstream video/audio runs long.
        cmd += [
            "-t", str(part_cap), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", "24", "-vf", "scale=1080:1920", str(part),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
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
    output = out_dir / "conversation.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-t", str(MAX_EPISODE_DURATION_S), "-c", "copy", str(output),
        ],
        check=True,
        capture_output=True,
    )

    # Burn timed speaker captions over the stitched video (best-effort: a
    # captionless conversation is still a valid deliverable).
    if any(c.get("dialogue") for c in cues):
        try:
            ass_file = out_dir / "captions.ass"
            ass_file.write_text(build_captions_ass(cues), encoding="utf-8")
            captioned = work / "conversation_captioned.mp4"
            ass_arg = str(ass_file).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            subprocess.run(
                [ffmpeg, "-y", "-i", str(output), "-t", str(MAX_EPISODE_DURATION_S),
                 "-vf", f"subtitles='{ass_arg}'",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                 "-movflags", "+faststart", str(captioned)],
                check=True, capture_output=True,
            )
            shutil.move(str(captioned), str(output))
        except subprocess.CalledProcessError:
            pass
    shutil.rmtree(work, ignore_errors=True)
    return "conversation.mp4"


def load_realistic_manifest(settings: Settings) -> dict[str, Any] | None:
    ensure_realistic_bank(settings)
    file = Path(settings.realistic_ref_dir) / "manifest.json"
    if not file.exists():
        return None
    manifest = json.loads(file.read_text(encoding="utf-8"))
    return None if manifest.get("dry_run") else manifest


def load_character_manifest(settings: Settings) -> dict[str, Any] | None:
    from youvsmany.media import characters  # local import to avoid cycles

    manifest = characters.existing_manifest(settings)
    return None if not manifest or manifest.get("dry_run") else manifest


async def generate(
    settings: Settings,
    *,
    base_url: str,
    segments: list[dict[str, Any]],
    resolution: str = "720P",
    dry_run: bool = False,
    stitch_output: bool = True,
    progress: Any | None = None,
) -> dict[str, Any]:
    if not dry_run and not settings.qwen_dashscope_api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY on the backend")
    if not dry_run and not ffmpeg_path():
        raise RuntimeError("ffmpeg is not installed on this backend")

    requested_segments = len(segments)
    segments = segments[:MAX_EPISODE_SEGMENTS]
    out_dir = video_out_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    realistic_manifest = load_realistic_manifest(settings)
    character_manifest = load_character_manifest(settings)

    manifest: dict[str, Any] = {
        "version": 1,
        "model": settings.qwen_video_edit_model,
        "resolution": resolution,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": dry_run,
        "realistic_bank": bool(realistic_manifest),
        "requested_segments": requested_segments,
        "segment_cap": MAX_EPISODE_SEGMENTS,
        "max_duration_s": MAX_EPISODE_DURATION_S,
        "segments": [],
        "conversation": None,
    }

    def flush() -> None:
        manifest["generated_count"] = sum(
            1 for s in manifest["segments"] if s.get("status") == "generated"
        )
        manifest["failed_count"] = sum(1 for s in manifest["segments"] if s.get("status") == "failed")
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    done = 0

    def report(path: str | None = None) -> None:
        if progress:
            progress(
                {
                    "current": done,
                    "total": len(segments),
                    "path": path,
                    "failed": manifest.get("failed_count", 0),
                }
            )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    async def run_segment(client: httpx.AsyncClient, index: int, segment: dict[str, Any]) -> dict[str, Any]:
        nonlocal done
        entry: dict[str, Any] = {
            "index": index,
            "segment_id": segment.get("segment_id", f"segment_{index:03d}"),
            "speaker_id": segment.get("speaker_id"),
            "prompt": segment["prompt"],
            "clip": segment["clip"],
            # Caption fields, burned into the stitched conversation.
            "dialogue": segment.get("dialogue"),
            "speaker_name": segment.get("speaker_name"),
            "speaker_color": segment.get("speaker_color"),
            "duration_s": segment.get("duration_s"),
        }
        video_rel = f"segments/{index:03d}_{entry['segment_id']}.mp4"
        try:
            media = build_media(settings, base_url, segment, realistic_manifest, character_manifest)
            entry["media"] = media
            if dry_run:
                entry["status"] = "planned"
                return entry
            async with semaphore:
                task_id = await create_task_with_retry(
                    client, settings, media=media, prompt=segment["prompt"], resolution=resolution
                )
                entry["task_id"] = task_id
                result = await poll_task(client, settings, task_id)
            video_url = result.get("output", {}).get("video_url")
            if not video_url:
                raise RuntimeError(f"no video_url in finished task: {result}")
            await download(client, video_url, out_dir / video_rel)
            entry["video"] = video_rel
            if segment.get("audio"):
                audio_rel = f"segments/{index:03d}_{entry['segment_id']}_audio"
                try:
                    await download(client, public_url(base_url, segment["audio"]), out_dir / audio_rel)
                    entry["audio_file"] = audio_rel
                except Exception:
                    pass  # audio mux is best-effort; the video is the deliverable
            entry["status"] = "generated"
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
        finally:
            done += 1
            report(entry.get("video") or entry["clip"])
        return entry

    report()
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        results = await asyncio.gather(
            *(run_segment(client, i, segment) for i, segment in enumerate(segments))
        )
    manifest["segments"] = sorted(results, key=lambda e: e["index"])
    flush()

    if not dry_run and stitch_output:
        try:
            manifest["conversation"] = stitch(settings, manifest["segments"], out_dir)
        except subprocess.CalledProcessError as exc:
            manifest["stitch_error"] = (exc.stderr or b"").decode("utf-8", "replace")[-2000:]
        flush()

    return manifest


def create_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "queued",
        "current": 0,
        "total": 0,
        "path": None,
        "failed": 0,
        "error": None,
        "manifest": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    VIDEO_JOBS[job_id] = job
    return job


async def run_job(job_id: str, settings: Settings, **kwargs: Any) -> None:
    job = VIDEO_JOBS[job_id]
    job["status"] = "running"
    job["updated_at"] = time.time()

    def progress(update: dict[str, Any]) -> None:
        job.update(update)
        job["updated_at"] = time.time()

    try:
        manifest = await generate(settings, progress=progress, **kwargs)
        entries = manifest.get("segments", [])
        generated = [s for s in entries if s.get("status") in {"generated", "planned"}]
        failures = [s for s in entries if s.get("status") == "failed"]
        job["failed"] = len(failures)
        job["status"] = (
            "failed" if failures and not generated else "partial" if failures else "succeeded"
        )
        if failures:
            job["error"] = failures[0].get("error")
        job["manifest"] = {
            "segments": len(entries),
            "generated": len(generated),
            "failed": len(failures),
            "conversation": manifest.get("conversation"),
            "manifest_url": "/media/video-edit/manifest.json",
            "files_url": "/media/video-edit/files/",
        }
    except Exception as exc:  # pragma: no cover - defensive job reporting
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
