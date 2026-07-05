"""Reusable character roster + persistent identity-image bank.

Instead of inventing a new visual identity per episode (slow: one image-edit
call per speaker per run, and random: every episode looks different), the show
owns a fixed roster of pre-described characters. Their photoreal identity
images are generated **once** into a persistent bank and reused forever:

- ``CHARACTER_ROSTER``: varied, gender-tagged character descriptions with
  stable seeds, defined in code so they never drift.
- ``select_character_visuals``: deterministic, seed-driven casting of roster
  members onto an episode's speakers (gender-matched, no duplicates), so the
  same brief+seed always shows the same faces while different seeds vary the
  panel.
- ``generate``: fills ``characters-v1/<roster_id>/identity.png`` via Qwen
  image-edit (identity portrait inside the canonical studio). Once generated,
  episodes need **zero** image calls: the bank ships in the repo
  (``frontend/assets/reference/characters-v1``) and seeds the served runtime
  bank the same way the realistic reference bank does.

Prompting follows the Qwen image-edit guidance used across this package:
subject first, then the (always identical) studio environment, then what must
stay fixed; plain wording; ``prompt_extend`` off; explicit "Image 1" labels.
"""

from __future__ import annotations

import asyncio
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
from youvsmany.media.reference_assets import (
    QwenRequestError,  # noqa: F401  (re-exported for callers/tests)
    download,
    image_data_url,
    output_urls,
    repo_root,
    request_edit_with_retry,
    source_ref_dir,
)
from youvsmany.media.studio import STUDIO_SCENE

# ---------------------------------------------------------------------------
# The roster: a bank of varied, reusable debate-show panelists.
#
# Descriptions vary age, heritage, styling and outfit color so a seeded pick
# gives every episode a distinct-looking panel, while each entry's wording and
# seed never change — the generated identity image is stable and cacheable.
# Outfits avoid pure black/white (flat on camera) and avoid repeating colors.
# ---------------------------------------------------------------------------

CHARACTER_ROSTER: list[dict[str, Any]] = [
    {
        "roster_id": "atlas",
        "label": "Atlas",
        "visual_presentation": "male",
        "seed": 520001,
        "description": (
            "confident man in his early 30s with short brown hair, clean modern "
            "styling, deep teal suit jacket over a dark navy shirt"
        ),
    },
    {
        "roster_id": "vega",
        "label": "Vega",
        "visual_presentation": "female",
        "seed": 520002,
        "description": (
            "composed woman in her late 20s with shoulder-length dark hair, deep "
            "red tailored blazer over a black top"
        ),
    },
    {
        "roster_id": "sable",
        "label": "Sable",
        "visual_presentation": "male",
        "seed": 520003,
        "description": (
            "analytical man in his mid 30s with a trimmed beard, burgundy "
            "tailored jacket over a charcoal shirt"
        ),
    },
    {
        "roster_id": "wren",
        "label": "Wren",
        "visual_presentation": "female",
        "seed": 520004,
        "description": (
            "poised woman in her early 30s with wavy auburn hair, rust-orange "
            "tailored jacket over a dark top"
        ),
    },
    {
        "roster_id": "onyx",
        "label": "Onyx",
        "visual_presentation": "male",
        "seed": 520005,
        "description": (
            "thoughtful Black man in his early 40s with short cropped hair and "
            "glasses, slate-blue suit jacket over a light grey shirt"
        ),
    },
    {
        "roster_id": "mira",
        "label": "Mira",
        "visual_presentation": "female",
        "seed": 520006,
        "description": (
            "sharp East Asian woman in her mid 30s with a neat black bob, "
            "emerald-green structured blazer over a cream top"
        ),
    },
    {
        "roster_id": "cedar",
        "label": "Cedar",
        "visual_presentation": "male",
        "seed": 520007,
        "description": (
            "warm South Asian man in his late 20s with thick dark hair, "
            "mustard-yellow knit blazer over a white shirt"
        ),
    },
    {
        "roster_id": "lyra",
        "label": "Lyra",
        "visual_presentation": "female",
        "seed": 520008,
        "description": (
            "confident Black woman in her late 30s with natural curly hair, "
            "royal-purple tailored blazer over a dark top"
        ),
    },
    {
        "roster_id": "flint",
        "label": "Flint",
        "visual_presentation": "male",
        "seed": 520009,
        "description": (
            "seasoned man in his mid 50s with silver-grey hair, forest-green "
            "corduroy jacket over an oatmeal shirt"
        ),
    },
    {
        "roster_id": "isla",
        "label": "Isla",
        "visual_presentation": "female",
        "seed": 520010,
        "description": (
            "bright Latina woman in her mid 20s with long dark wavy hair, "
            "cobalt-blue blazer over a soft grey top"
        ),
    },
    {
        "roster_id": "north",
        "label": "North",
        "visual_presentation": "male",
        "seed": 520011,
        "description": (
            "steady Middle Eastern man in his late 30s with short dark hair and "
            "light stubble, camel-brown blazer over a dark green shirt"
        ),
    },
    {
        "roster_id": "juno",
        "label": "Juno",
        "visual_presentation": "female",
        "seed": 520012,
        "description": (
            "witty woman in her early 50s with a sleek silver-blonde crop, "
            "plum-colored suit jacket over a charcoal top"
        ),
    },
]

ROSTER_BY_ID = {entry["roster_id"]: entry for entry in CHARACTER_ROSTER}


def identity_image_rel(roster_id: str) -> str:
    return f"{roster_id}/identity.png"


# --- deterministic episode casting -----------------------------------------


def select_character_visuals(
    speakers: list[tuple[str, str]], seed: int
) -> dict[str, dict[str, Any]]:
    """Deterministically cast roster members onto episode speakers.

    ``speakers`` is ``[(character_id, visual_presentation), ...]`` in cast
    order. Gender-matched where the cast specifies one; never assigns the same
    roster member twice; the same seed always produces the same panel and a
    different seed shuffles it.
    """
    rng = random.Random(seed * 7919 + 17)
    pools: dict[str, list[dict[str, Any]]] = {"male": [], "female": []}
    for entry in CHARACTER_ROSTER:
        pools[entry["visual_presentation"]].append(entry)
    for pool in pools.values():
        rng.shuffle(pool)

    assigned: dict[str, dict[str, Any]] = {}
    for character_id, presentation in speakers:
        pool = pools.get(presentation)
        if not pool:
            # Neutral/unknown presentation: draw from whichever pool is fuller.
            pool = max(pools.values(), key=len)
        if not pool:  # roster exhausted (cast larger than roster)
            continue
        assigned[character_id] = pool.pop(0)
    return assigned


def character_ref_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "roster_id": entry["roster_id"],
        "label": entry["label"],
        "visual_presentation": entry["visual_presentation"],
        "identity_image": identity_image_rel(entry["roster_id"]),
        "description": entry["description"],
        "seed": entry["seed"],
    }


# --- persistent bank locations ----------------------------------------------


def packaged_character_bank_dir() -> Path:
    configured = os.getenv("YVM_PACKAGED_CHARACTER_BANK_DIR")
    if configured:
        return Path(configured)
    return repo_root() / "frontend" / "assets" / "reference" / "characters-v1"


def character_bank_dir(settings: Settings) -> Path:
    return Path(settings.character_bank_dir)


def manifest_path(settings: Settings) -> Path:
    return character_bank_dir(settings) / "manifest.json"


def ensure_character_bank(settings: Settings) -> Path | None:
    """Seed the served runtime bank from the packaged repo bank (same
    redeploy-survival pattern as the realistic reference bank)."""
    out_dir = character_bank_dir(settings)
    out_manifest = out_dir / "manifest.json"
    if out_manifest.exists():
        return out_dir
    packaged_dir = packaged_character_bank_dir()
    if not (packaged_dir / "manifest.json").exists():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(packaged_dir, out_dir, dirs_exist_ok=True)
    return out_dir


def existing_manifest(settings: Settings) -> dict[str, Any] | None:
    ensure_character_bank(settings)
    file = manifest_path(settings)
    if not file.exists():
        return None
    return json.loads(file.read_text(encoding="utf-8"))


def status(settings: Settings) -> dict[str, Any]:
    current = existing_manifest(settings)
    characters = current.get("characters", []) if current else []
    generated = [
        c for c in characters if c.get("status") in {"generated", "existing"} and c.get("identity")
    ]
    failed = [c for c in characters if c.get("status") == "failed"]
    available = bool(current and not current.get("dry_run") and generated)
    return {
        "available": available,
        "roster_count": len(CHARACTER_ROSTER),
        "generated_count": len(generated),
        "failed_count": len(failed),
        "manifest_url": "/media/character-bank/manifest.json" if available else None,
        "files_url": "/media/character-bank/files/",
        "model": settings.qwen_image_edit_model,
        "qwen_ready": bool(settings.qwen_dashscope_api_key),
    }


# --- identity generation ------------------------------------------------------

# Seated pose starters from the existing 9:16 bank, one per presentation, so
# every identity portrait shares the same seat, desk line and camera height.
POSE_STARTERS = {
    "male": "main_speaker/protagonist/close/starter.png",
    "female": "second_speaker/challenger_1/close/starter.png",
}


def identity_prompt_for(entry: dict[str, Any]) -> str:
    return " ".join(
        [
            "Use Image 1 only as the pose, seat position, framing and camera-angle reference.",
            "Create a realistic 9:16 cinematic live-action portrait of a debate-show panelist:",
            f"{entry['description']}.",
            f"Environment: {STUDIO_SCENE}.",
            "Keep the seated pose, desk line and camera height from Image 1 unchanged.",
            "Style: photorealistic broadcast photography, natural lighting, gentle depth of field.",
            "No captions, no lower thirds, no text, no logos, no watermark.",
        ]
    )


def identity_fallback_prompt_for(entry: dict[str, Any]) -> str:
    """Plain wording used when moderation rejects the main prompt."""
    return (
        f"Turn this into a realistic photo of a television debate panelist: "
        f"{entry['description']}. Same pose, seat and camera angle as the input image. "
        f"Setting: {STUDIO_SCENE}. Vertical 9:16 framing. No text or logos."
    )


JOBS: dict[str, dict[str, Any]] = {}

CONCURRENCY = int(os.getenv("YVM_IMAGE_CONCURRENCY", "2"))


async def generate(
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int = 0,
    overwrite: bool = False,
    size: str = "1080*1920",
    concurrency: int = CONCURRENCY,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Fill the persistent identity bank, one image per roster character.

    Independent shots: one moderation rejection or transient failure records a
    failed character and moves on. The manifest is rewritten after every
    character so partial banks are usable and re-runs only fill gaps.
    """
    if not dry_run and not settings.qwen_dashscope_api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY on the backend")

    out_dir = character_bank_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    roster = CHARACTER_ROSTER[:limit] if limit and limit > 0 else CHARACTER_ROSTER

    manifest: dict[str, Any] = {
        "version": 1,
        "model": settings.qwen_image_edit_model,
        "format": "9:16",
        "size": size,
        "studio_scene": STUDIO_SCENE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": dry_run,
        "characters": [],
    }
    results: dict[int, dict[str, Any]] = {}
    counters = {"done": 0, "failed": 0}

    def flush() -> None:
        manifest["characters"] = [results[i] for i in sorted(results)]
        manifest["generated_count"] = sum(
            1 for c in manifest["characters"] if c.get("status") in {"generated", "existing"}
        )
        manifest["failed_count"] = sum(
            1 for c in manifest["characters"] if c.get("status") == "failed"
        )
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    async def run_character(client: httpx.AsyncClient, index: int, entry: dict[str, Any]) -> None:
        output_rel = identity_image_rel(entry["roster_id"])
        output_file = out_dir / output_rel
        base = {
            **character_ref_payload(entry),
            "prompt": identity_prompt_for(entry),
        }

        if output_file.exists() and not overwrite:
            results[index] = {**base, "identity": output_rel, "status": "existing"}
        elif dry_run:
            results[index] = {**base, "identity": output_rel, "status": "planned"}
        else:
            pose_file = source_ref_dir() / POSE_STARTERS[entry["visual_presentation"]]
            try:
                result, used_prompt = await request_edit_with_retry(
                    client,
                    settings,
                    input_images=[image_data_url(pose_file)],
                    prompt=identity_prompt_for(entry),
                    fallback_prompt=identity_fallback_prompt_for(entry),
                    seed=int(entry["seed"]),
                    size=size,
                )
                urls = output_urls(result)
                if not urls:
                    raise RuntimeError(f"No output URL in response: {result}")
                await download(client, urls[0], output_file)
                results[index] = {
                    **base, "identity": output_rel, "prompt": used_prompt, "status": "generated",
                }
            except Exception as exc:
                counters["failed"] += 1
                results[index] = {**base, "status": "failed", "error": str(exc)}

        counters["done"] += 1
        if progress:
            progress({
                "current": counters["done"], "total": len(roster),
                "path": output_rel, "failed": counters["failed"],
            })
        flush()

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def guarded(client: httpx.AsyncClient, index: int, entry: dict[str, Any]) -> None:
        async with semaphore:
            await run_character(client, index, entry)

    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        await asyncio.gather(*(guarded(client, i, e) for i, e in enumerate(roster)))

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
        characters = manifest.get("characters", [])
        generated = [c for c in characters if c.get("status") in {"generated", "existing", "planned"}]
        failures = [c for c in characters if c.get("status") == "failed"]
        job["failed"] = len(failures)
        job["status"] = (
            "failed" if failures and not generated else "partial" if failures else "succeeded"
        )
        if failures:
            job["error"] = failures[0].get("error")
        job["manifest"] = {
            "characters": len(characters),
            "generated": len(generated),
            "failed": len(failures),
            "manifest_url": "/media/character-bank/manifest.json",
            "files_url": "/media/character-bank/files/",
        }
    except Exception as exc:  # pragma: no cover - defensive job reporting
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
