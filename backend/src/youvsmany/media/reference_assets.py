"""Qwen-backed realistic reference image generation.

The frontend owns the starter reference bank. The backend owns secret-bearing
calls to Qwen Cloud and writes generated realistic images into a served media
directory so browsers can use them without seeing API keys.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from youvsmany.config import Settings


SPEAKER_PROFILES: dict[str, dict[str, Any]] = {
    "protagonist": {
        "slot": "main_speaker",
        "label": "Main Speaker",
        "seed": 411001,
        "description": (
            "confident male-presenting debate contestant, early 30s, clean modern styling, "
            "deep teal suit jacket over a dark shirt, calm focused expression"
        ),
    },
    "challenger_1": {
        "slot": "second_speaker",
        "label": "Second Speaker",
        "seed": 411101,
        "description": (
            "female-presenting debate contestant, late 20s, composed and sharp, deep red "
            "tailored blazer over a black top, expressive but controlled presence"
        ),
    },
    "challenger_2": {
        "slot": "third_speaker",
        "label": "Third Speaker",
        "seed": 411201,
        "description": (
            "male-presenting debate contestant, mid 30s, analytical and intense, burgundy "
            "tailored jacket over a charcoal shirt, direct steady posture"
        ),
    },
    "challenger_3": {
        "slot": "fourth_speaker",
        "label": "Fourth Speaker",
        "seed": 411301,
        "description": (
            "female-presenting debate contestant, early 30s, poised and skeptical, rust-red "
            "tailored jacket over a dark top, cinematic debate-show presence"
        ),
    },
}

SHOT_DESCRIPTIONS = {
    "intro_wide": "vertical establishing shot of the whole debate table and panel in a cinematic studio",
    "intro_table": "vertical table-level opening shot with the debate desk leading the eye into the room",
    "intro_panel": "vertical opening shot of the opposing speaker bench in a premium studio debate set",
    "close": "tight vertical upper-body speaking reference, head and shoulders prominent",
    "medium": "vertical medium upper-body speaking reference, chest and arms visible, table edge in foreground",
    "profile": "vertical side profile speaking reference, cinematic panel-discussion angle",
    "over_table": "vertical over-table speaking reference with depth across the debate desk",
}

JOBS: dict[str, dict[str, Any]] = {}


def repo_root() -> Path:
    # backend/src/youvsmany/media/reference_assets.py -> repo root
    return Path(__file__).resolve().parents[4]


def source_ref_dir() -> Path:
    configured = os.getenv("YVM_REFERENCE_SOURCE_DIR")
    if configured:
        return Path(configured)
    return repo_root() / "frontend" / "assets" / "reference" / "vertical-v1"


def realistic_ref_dir(settings: Settings) -> Path:
    return Path(settings.realistic_ref_dir)


def manifest_path(settings: Settings) -> Path:
    return realistic_ref_dir(settings) / "manifest.json"


def read_json(file: Path) -> dict[str, Any]:
    return json.loads(file.read_text(encoding="utf-8"))


def source_manifest() -> dict[str, Any]:
    return read_json(source_ref_dir() / "manifest.json")


def existing_manifest(settings: Settings) -> dict[str, Any] | None:
    file = manifest_path(settings)
    if not file.exists():
        return None
    return read_json(file)


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
    available = bool(current and not current.get("dry_run") and generated)
    return {
        "available": available,
        "source_count": len(src.get("shots", [])),
        "generated_count": len(generated),
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
        else "Use image 1 as the locked identity/style reference for the person, and image 2 as the exact pose, "
        "framing, camera angle and table composition reference."
    )
    return " ".join(
        [
            identity_line,
            "Create a realistic 9:16 cinematic live-action frame for a premium AI debate show.",
            f"Subject: {profile['description']}.",
            f"Shot: {shot_text}.",
            "Preserve the same speaker slot, seating position, body orientation, table placement, lighting direction and camera perspective from the source reference.",
            "Keep the character visually consistent across all outputs for this speaker: same face structure, outfit color family, hairstyle silhouette, body type and overall identity.",
            "Make it photorealistic: real human proportions, natural skin, realistic fabric, cinematic studio lighting, polished broadcast set, shallow but usable depth of field.",
            "No captions, no subtitles, no lower thirds, no text, no logos, no watermark, no UI elements.",
        ]
    )


def negative_prompt() -> str:
    return ", ".join(
        [
            "cartoon",
            "3d render",
            "toy",
            "plastic",
            "robot",
            "mannequin",
            "helmet",
            "faceless",
            "extra limbs",
            "distorted hands",
            "text",
            "caption",
            "subtitle",
            "logo",
            "watermark",
            "cropped head",
            "out of frame subject",
        ]
    )


def image_data_url(file: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(file.read_bytes()).decode("ascii")


def build_plan(limit: int = 0) -> list[dict[str, Any]]:
    src_manifest = source_manifest()
    shots = src_manifest.get("shots", [])
    selected = shots[:limit] if limit and limit > 0 else shots
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
        output_rel = str(Path(shot["starter"]).parent / "realistic.png").replace("\\", "/")
        out.append(
            {
                "shot": shot,
                "source_starter": source_starter,
                "identity_starter": identity_starter,
                "output_rel": output_rel,
                "seed": stable_seed(shot),
                "prompt": prompt_for(shot),
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
    settings: Settings,
    input_images: list[str],
    prompt: str,
    seed: int,
    size: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
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
                    "prompt_extend": True,
                    "negative_prompt": negative_prompt(),
                },
            },
        )
    data = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"Qwen request failed {response.status_code}: {data}")
    return data


async def download(url: str, file: Path) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(url)
    response.raise_for_status()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(response.content)


async def generate(
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int = 0,
    overwrite: bool = False,
    delay_ms: int = 33000,
    size: str = "1080*1920",
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

    for index, item in enumerate(plan):
        output_file = out_dir / item["output_rel"]
        exists = output_file.exists()
        if progress:
            progress({"current": index + 1, "total": len(plan), "path": item["output_rel"]})

        if exists and not overwrite:
            manifest["shots"].append(
                {
                    **item["shot"],
                    "realistic": item["output_rel"],
                    "seed": item["seed"],
                    "prompt": item["prompt"],
                    "status": "existing",
                }
            )
            continue

        if dry_run:
            manifest["shots"].append(
                {
                    **item["shot"],
                    "realistic": item["output_rel"],
                    "seed": item["seed"],
                    "prompt": item["prompt"],
                    "status": "planned",
                }
            )
            continue

        input_images = (
            [image_data_url(item["source_starter"])]
            if item["identity_starter"] == item["source_starter"]
            else [image_data_url(item["identity_starter"]), image_data_url(item["source_starter"])]
        )
        result = await request_edit(
            settings,
            input_images=input_images,
            prompt=item["prompt"],
            seed=item["seed"],
            size=size,
        )
        urls = output_urls(result)
        if not urls:
            raise RuntimeError(f"No output URL for {item['output_rel']}: {result}")
        await download(urls[0], output_file)
        manifest["shots"].append(
            {
                **item["shot"],
                "realistic": item["output_rel"],
                "seed": item["seed"],
                "prompt": item["prompt"],
                "status": "generated",
            }
        )

        if index < len(plan) - 1 and delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def create_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "queued",
        "current": 0,
        "total": 0,
        "path": None,
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
        job["status"] = "succeeded"
        job["manifest"] = {
            "shots": len(manifest.get("shots", [])),
            "manifest_url": "/media/realistic-refs/manifest.json",
            "files_url": "/media/realistic-refs/files/",
        }
    except Exception as exc:  # pragma: no cover - defensive job reporting
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
