"""Qwen-backed realistic reference image generation.

The frontend owns the starter reference bank. The backend owns secret-bearing
calls to Qwen Cloud and writes generated realistic images into a served media
directory so browsers can use them without seeing API keys.

Generation strategy:
- Intro and per-speaker ``close`` shots are generated first. The close shot is
  the identity anchor: once its realistic image exists, every other angle for
  that speaker uses the *generated* close image as the identity reference,
  which keeps the character consistent from a real photo instead of the
  stylized starter frame.
- Each shot is generated independently: one moderation rejection or transient
  error records a failed shot and moves on instead of killing the whole job.
- The manifest is rewritten after every shot, so partial banks are usable
  immediately and a re-run (overwrite=False) only fills in what is missing.

DashScope moderation (``DataInspectionFailed``) scans prompt text too, so
prompts avoid known false-positive terms (skin/limbs/body-part words) and
``prompt_extend`` stays off — the server-side rewritten prompt is re-inspected
and turns deterministic prompts into coin flips.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from youvsmany.config import Settings
from youvsmany.media.studio import STUDIO_SCENE


SPEAKER_PROFILES: dict[str, dict[str, Any]] = {
    "protagonist": {
        "slot": "main_speaker",
        "label": "Main Speaker",
        "seed": 411001,
        "description": (
            "confident man in his early 30s, clean modern styling, deep teal suit "
            "jacket over a dark shirt, calm focused expression"
        ),
    },
    "challenger_1": {
        "slot": "second_speaker",
        "label": "Second Speaker",
        "seed": 411101,
        "description": (
            "composed woman in her late 20s, sharp confident presence, deep red "
            "tailored blazer over a black top"
        ),
    },
    "challenger_2": {
        "slot": "third_speaker",
        "label": "Third Speaker",
        "seed": 411201,
        "description": (
            "analytical man in his mid 30s, burgundy tailored jacket over a "
            "charcoal shirt, steady direct posture"
        ),
    },
    "challenger_3": {
        "slot": "fourth_speaker",
        "label": "Fourth Speaker",
        "seed": 411301,
        "description": (
            "poised woman in her early 30s, rust-red tailored jacket over a dark "
            "top, confident debate-show presence"
        ),
    },
}

SHOT_DESCRIPTIONS = {
    "intro_wide": "vertical wide view of the whole debate table and panel in a cinematic studio",
    "intro_table": "vertical table-level opening view with the debate desk leading the eye into the room",
    "intro_panel": "vertical opening view of the opposing speaker bench in a premium studio debate set",
    "close": "tight vertical upper-body speaking view, head and shoulders prominent",
    "medium": "vertical medium upper-body speaking view, chest and arms visible, table edge in foreground",
    "profile": "vertical side-profile speaking view, cinematic panel-discussion angle",
    "over_table": "vertical over-table speaking view with depth across the debate desk",
}

# DashScope error codes worth retrying with backoff (rate limits / transient).
RETRYABLE_CODES = {
    "Throttling",
    "Throttling.RateQuota",
    "Throttling.AllocationQuota",
    "RequestTimeOut",
    "InternalError",
    "SystemError",
    "InternalError.Algo",
}

JOBS: dict[str, dict[str, Any]] = {}


class QwenRequestError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"Qwen request failed {status} [{code}]: {message}")
        self.status = status
        self.code = code
        self.retryable = code in RETRYABLE_CODES or status >= 500


def repo_root() -> Path:
    # backend/src/youvsmany/media/reference_assets.py -> repo root
    return Path(__file__).resolve().parents[4]


def source_ref_dir() -> Path:
    configured = os.getenv("YVM_REFERENCE_SOURCE_DIR")
    if configured:
        return Path(configured)
    return repo_root() / "frontend" / "assets" / "reference" / "vertical-v1"


def packaged_realistic_ref_dir() -> Path:
    configured = os.getenv("YVM_PACKAGED_REALISTIC_REF_DIR")
    if configured:
        return Path(configured)
    return repo_root() / "frontend" / "assets" / "reference" / "realistic-v1"


def realistic_ref_dir(settings: Settings) -> Path:
    return Path(settings.realistic_ref_dir)


def manifest_path(settings: Settings) -> Path:
    return realistic_ref_dir(settings) / "manifest.json"


def read_json(file: Path) -> dict[str, Any]:
    return json.loads(file.read_text(encoding="utf-8"))


def source_manifest() -> dict[str, Any]:
    return read_json(source_ref_dir() / "manifest.json")


def existing_manifest(settings: Settings) -> dict[str, Any] | None:
    ensure_realistic_bank(settings)
    file = manifest_path(settings)
    if not file.exists():
        return None
    return read_json(file)


def ensure_realistic_bank(settings: Settings) -> Path | None:
    """Seed the served runtime bank from the packaged frontend bank.

    Railway's filesystem is ephemeral, so generated files under ``runs/`` vanish
    on redeploy. The repo now carries a persisted realistic bank in
    ``frontend/assets/reference/realistic-v1``; copy it into the mounted media
    directory when the runtime directory has no manifest yet. Live generation can
    still overwrite/fill the runtime directory later.
    """
    out_dir = realistic_ref_dir(settings)
    out_manifest = out_dir / "manifest.json"
    if out_manifest.exists():
        return out_dir
    packaged_dir = packaged_realistic_ref_dir()
    packaged_manifest = packaged_dir / "manifest.json"
    if not packaged_manifest.exists():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(packaged_dir, out_dir, dirs_exist_ok=True)
    return out_dir


def path_ref(from_dir: Path, to_path: Path) -> str:
    try:
        return os.path.relpath(to_path, from_dir).replace("\\", "/")
    except ValueError:
        return to_path.as_posix()


def status(settings: Settings) -> dict[str, Any]:
    src = source_manifest()
    current = existing_manifest(settings)
    shots = current.get("shots", []) if current else []
    generated = [
        shot for shot in shots if shot.get("status") in {"generated", "existing"} and shot.get("realistic")
    ]
    failed = [shot for shot in shots if shot.get("status") == "failed"]
    available = bool(current and not current.get("dry_run") and generated)
    return {
        "available": available,
        "source_count": len(src.get("shots", [])),
        "generated_count": len(generated),
        "failed_count": len(failed),
        "manifest_url": "/media/realistic-refs/manifest.json" if available else None,
        "files_url": "/media/realistic-refs/files/",
        "model": settings.qwen_image_edit_model,
        "qwen_ready": bool(settings.qwen_dashscope_api_key),
    }


def stable_seed(shot: dict[str, Any]) -> int:
    profile = SPEAKER_PROFILES.get(shot.get("speakerId"), SPEAKER_PROFILES["protagonist"])
    shot_offset = sum(ord(ch) for ch in str(shot.get("group", "") + shot.get("id", "")))
    return int(profile["seed"]) + shot_offset


def prompt_for(shot: dict[str, Any]) -> str:
    profile = SPEAKER_PROFILES.get(shot.get("speakerId"), SPEAKER_PROFILES["protagonist"])
    is_intro = shot.get("group") == "intro"
    shot_text = (
        SHOT_DESCRIPTIONS.get(shot.get("id"))
        or SHOT_DESCRIPTIONS.get(shot.get("shot"))
        or "vertical cinematic debate-show reference"
    )
    identity_line = (
        "Use the input image as the exact composition reference for the debate room, seating layout, "
        "table geometry and camera angle."
        if is_intro
        else "Use image 1 as the locked identity reference for the person, and image 2 as the exact pose, "
        "framing, camera angle and table composition reference."
    )
    return " ".join(
        [
            identity_line,
            "Create a realistic 9:16 cinematic live-action frame for a premium televised debate show.",
            f"Subject: {profile['description']}.",
            # The environment line is identical across every prompt in the
            # pipeline (see media/studio.py) so all shots and all characters
            # land in the same room.
            f"Environment: {STUDIO_SCENE}.",
            f"Camera: {shot_text}.",
            "Preserve the same speaker position, body orientation, table placement, lighting direction and camera perspective from the source reference.",
            "Keep this speaker visually consistent across every image: same facial features, hairstyle, outfit colors and overall identity.",
            "Style: photorealistic broadcast photography, natural lighting, realistic fabric and materials, gentle depth of field.",
            "No captions, no subtitles, no lower thirds, no text, no logos, no watermark.",
        ]
    )


def fallback_prompt_for(shot: dict[str, Any]) -> str:
    """Deliberately plain wording used when moderation rejects the main prompt."""
    if shot.get("group") == "intro":
        return (
            "Turn this image into a realistic photo of the same television debate studio. "
            f"Setting: {STUDIO_SCENE}. "
            "Keep the same composition, seating layout, table and camera angle. "
            "Vertical 9:16 framing. No text or logos."
        )
    return (
        "Turn this into a realistic photo of a professional television debate speaker. "
        f"Setting: {STUDIO_SCENE}. "
        "Keep the same pose, seat position, outfit colors and camera angle as the reference images. "
        "Vertical 9:16 framing. No text or logos."
    )


def negative_prompt() -> str:
    return ", ".join(
        [
            "cartoon",
            "anime",
            "illustration",
            "3d render",
            "toy",
            "plastic",
            "doll",
            "low quality",
            "blurry",
            "text",
            "caption",
            "subtitle",
            "logo",
            "watermark",
        ]
    )


def image_data_url(file: Path) -> str:
    data = file.read_bytes()
    mime = "image/jpeg" if data[:2] == b"\xff\xd8" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def plan_priority(shot: dict[str, Any]) -> int:
    """Intros and identity-anchor close shots first, dependent angles after."""
    if shot.get("group") == "intro":
        return 0
    if shot.get("id") == "close":
        return 1
    return 2


def build_plan(limit: int = 0) -> list[dict[str, Any]]:
    src_manifest = source_manifest()
    shots = src_manifest.get("shots", [])
    selected = shots[:limit] if limit and limit > 0 else shots
    selected = sorted(selected, key=plan_priority)
    out: list[dict[str, Any]] = []
    for shot in selected:
        source_starter = source_ref_dir() / shot["starter"]
        identity_shot = next(
            (
                candidate
                for candidate in shots
                if candidate.get("speakerId") == shot.get("speakerId") and candidate.get("id") == "close"
            ),
            None,
        )
        identity_starter = source_ref_dir() / identity_shot["starter"] if identity_shot else source_starter
        identity_output_rel = (
            str(Path(identity_shot["starter"]).parent / "realistic.png").replace("\\", "/")
            if identity_shot
            else None
        )
        output_rel = str(Path(shot["starter"]).parent / "realistic.png").replace("\\", "/")
        out.append(
            {
                "shot": shot,
                "source_starter": source_starter,
                "identity_starter": identity_starter,
                "identity_output_rel": identity_output_rel,
                "output_rel": output_rel,
                "seed": stable_seed(shot),
                "prompt": prompt_for(shot),
                "fallback_prompt": fallback_prompt_for(shot),
            }
        )
    return out


def output_urls(result: dict[str, Any]) -> list[str]:
    choices = result.get("output", {}).get("choices", [])
    urls: list[str] = []
    for choice in choices:
        for item in choice.get("message", {}).get("content", []):
            url = item.get("image")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.append(url)
    return urls


async def request_edit(
    client: httpx.AsyncClient,
    settings: Settings,
    input_images: list[str],
    prompt: str,
    seed: int,
    size: str,
) -> dict[str, Any]:
    response = await client.post(
        settings.qwen_image_edit_url,
        headers={
            "Authorization": f"Bearer {settings.qwen_dashscope_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.qwen_image_edit_model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            *({"image": image} for image in input_images),
                            {"text": prompt},
                        ],
                    }
                ],
            },
            "parameters": {
                "n": 1,
                "size": size,
                "seed": seed,
                "watermark": False,
                # Off on purpose: the server-side rewritten prompt is re-run
                # through content inspection and randomly trips it.
                "prompt_extend": False,
                "negative_prompt": negative_prompt(),
            },
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
    return data


async def request_edit_with_retry(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    input_images: list[str],
    prompt: str,
    fallback_prompt: str,
    seed: int,
    size: str,
    max_attempts: int = 7,
) -> tuple[dict[str, Any], str]:
    """Retry throttles/transients with backoff; retry moderation rejections once
    with the plain fallback prompt. Returns (result, prompt actually used)."""
    active_prompt = prompt
    attempt = 0
    while True:
        attempt += 1
        try:
            result = await request_edit(client, settings, input_images, active_prompt, seed, size)
            return result, active_prompt
        except QwenRequestError as exc:
            if exc.code == "DataInspectionFailed" and active_prompt != fallback_prompt:
                active_prompt = fallback_prompt
                continue
            if not exc.retryable or attempt >= max_attempts:
                raise
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= max_attempts:
                raise
        await asyncio.sleep(min(2**attempt * 2, 45) + random.uniform(0, 1))


async def download(client: httpx.AsyncClient, url: str, file: Path) -> None:
    response = await client.get(url)
    response.raise_for_status()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(response.content)


# How many image-edit requests may be in flight at once. Identity-anchor
# dependencies are respected by running each priority tier to completion before
# the next starts, so shots inside a tier are safe to parallelize. Kept low (2)
# because the qwen-image-edit-max rate quota on this account throttles (429) at
# 3 concurrent; the retry/backoff still absorbs occasional throttles at 2.
CONCURRENCY = int(os.getenv("YVM_IMAGE_CONCURRENCY", "2"))


async def generate(
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int = 0,
    overwrite: bool = False,
    delay_ms: int = 2000,
    size: str = "1080*1920",
    concurrency: int = CONCURRENCY,
    progress: Any | None = None,
) -> dict[str, Any]:
    if not dry_run and not settings.qwen_dashscope_api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY on the backend")

    out_dir = realistic_ref_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = build_plan(limit)

    manifest: dict[str, Any] = {
        "version": 1,
        "source_bank": path_ref(out_dir, source_ref_dir()),
        "model": settings.qwen_image_edit_model,
        "provider": settings.qwen_image_edit_model,
        "format": "9:16",
        "size": size,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": dry_run,
        "shots": [],
    }
    # Keep manifest order stable (by plan index) even though tasks finish out
    # of order under concurrency.
    results: dict[int, dict[str, Any]] = {}
    counters = {"done": 0, "failed": 0}

    def flush() -> None:
        manifest["shots"] = [results[i] for i in sorted(results)]
        manifest["generated_count"] = sum(
            1 for s in manifest["shots"] if s.get("status") in {"generated", "existing"}
        )
        manifest["failed_count"] = sum(1 for s in manifest["shots"] if s.get("status") == "failed")
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    data_url_cache: dict[Path, str] = {}

    def cached_data_url(file: Path) -> str:
        if file not in data_url_cache:
            data_url_cache[file] = image_data_url(file)
        return data_url_cache[file]

    async def run_shot(client: httpx.AsyncClient, index: int, item: dict[str, Any]) -> None:
        output_file = out_dir / item["output_rel"]

        if output_file.exists() and not overwrite:
            results[index] = {
                **item["shot"], "realistic": item["output_rel"], "seed": item["seed"],
                "prompt": item["prompt"], "status": "existing",
            }
        elif dry_run:
            results[index] = {
                **item["shot"], "realistic": item["output_rel"], "seed": item["seed"],
                "prompt": item["prompt"], "status": "planned",
            }
        else:
            # Prefer the already-generated realistic close shot as the identity
            # anchor; earlier tiers finish before this one starts, so it exists.
            identity_realistic = (
                out_dir / item["identity_output_rel"] if item["identity_output_rel"] else None
            )
            identity_file = (
                identity_realistic
                if identity_realistic and identity_realistic.exists() and identity_realistic != output_file
                else item["identity_starter"]
            )
            if identity_file == item["source_starter"] or identity_realistic == output_file:
                input_images = [cached_data_url(item["source_starter"])]
            else:
                input_images = [
                    cached_data_url(identity_file),
                    cached_data_url(item["source_starter"]),
                ]
            try:
                result, used_prompt = await request_edit_with_retry(
                    client, settings, input_images=input_images, prompt=item["prompt"],
                    fallback_prompt=item["fallback_prompt"], seed=item["seed"], size=size,
                )
                urls = output_urls(result)
                if not urls:
                    raise RuntimeError(f"No output URL in response: {result}")
                await download(client, urls[0], output_file)
                results[index] = {
                    **item["shot"], "realistic": item["output_rel"], "seed": item["seed"],
                    "prompt": used_prompt, "status": "generated",
                }
            except Exception as exc:
                counters["failed"] += 1
                results[index] = {
                    **item["shot"], "seed": item["seed"], "prompt": item["prompt"],
                    "status": "failed", "error": str(exc),
                }

        counters["done"] += 1
        if progress:
            progress({
                "current": counters["done"], "total": len(plan),
                "path": item["output_rel"], "failed": counters["failed"],
            })
        flush()

    # Group the (priority-sorted) plan into tiers so a dependent angle never
    # runs before its speaker's realistic close image has been written.
    tiers: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for index, item in enumerate(plan):
        tiers.setdefault(plan_priority(item["shot"]), []).append((index, item))

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def guarded(client: httpx.AsyncClient, index: int, item: dict[str, Any]) -> None:
        async with semaphore:
            await run_shot(client, index, item)

    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        for _priority in sorted(tiers):
            await asyncio.gather(*(guarded(client, i, it) for i, it in tiers[_priority]))

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
        shots = manifest.get("shots", [])
        generated = [s for s in shots if s.get("status") in {"generated", "existing", "planned"}]
        failures = [s for s in shots if s.get("status") == "failed"]
        job["failed"] = len(failures)
        job["status"] = (
            "failed" if failures and not generated else "partial" if failures else "succeeded"
        )
        if failures:
            job["error"] = failures[0].get("error")
        job["manifest"] = {
            "shots": len(shots),
            "generated": len(generated),
            "failed": len(failures),
            "manifest_url": "/media/realistic-refs/manifest.json",
            "files_url": "/media/realistic-refs/files/",
        }
    except Exception as exc:  # pragma: no cover - defensive job reporting
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
