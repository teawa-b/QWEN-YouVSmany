"""Persistent character roster: selection determinism, prompt consistency,
scene-manifest wiring, API dry-run, and the backend/frontend studio-scene sync."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi.testclient import TestClient

from youvsmany.adapters.mock_provider import MockProvider
from youvsmany.agents import orchestrator
from youvsmany.api.main import app
from youvsmany.config import Settings
from youvsmany.contracts.brief import ShowBrief
from youvsmany.media import characters
from youvsmany.media.reference_assets import fallback_prompt_for, prompt_for
from youvsmany.media.studio import STUDIO_SCENE

REPO_ROOT = Path(__file__).resolve().parents[2]

SPEAKERS = [
    ("protagonist", "male"),
    ("challenger_1", "female"),
    ("challenger_2", "female"),
    ("challenger_3", "male"),
]


def test_roster_is_varied_and_stable():
    ids = [e["roster_id"] for e in characters.CHARACTER_ROSTER]
    seeds = [e["seed"] for e in characters.CHARACTER_ROSTER]
    assert len(ids) >= 12, "roster should offer a real pool of reusable characters"
    assert len(set(ids)) == len(ids)
    assert len(set(seeds)) == len(seeds), "stable unique seeds keep identities cacheable"
    genders = {e["visual_presentation"] for e in characters.CHARACTER_ROSTER}
    assert genders == {"male", "female"}
    for gender in genders:
        pool = [e for e in characters.CHARACTER_ROSTER if e["visual_presentation"] == gender]
        assert len(pool) >= 4, f"need enough {gender} options for a 1+5 cast"


def test_selection_is_deterministic_gender_matched_and_unique():
    first = characters.select_character_visuals(SPEAKERS, seed=3)
    again = characters.select_character_visuals(SPEAKERS, seed=3)
    assert {k: v["roster_id"] for k, v in first.items()} == {
        k: v["roster_id"] for k, v in again.items()
    }
    assert len(first) == len(SPEAKERS)
    picked = [v["roster_id"] for v in first.values()]
    assert len(set(picked)) == len(picked), "no roster member may appear twice in one episode"
    for character_id, presentation in SPEAKERS:
        assert first[character_id]["visual_presentation"] == presentation


def test_selection_varies_with_seed():
    panels = {
        tuple(v["roster_id"] for v in characters.select_character_visuals(SPEAKERS, seed=s).values())
        for s in range(6)
    }
    assert len(panels) > 1, "different seeds should produce different panels"


def test_scene_manifest_carries_character_refs():
    ep = orchestrator.run_full(
        ShowBrief(topic="Pineapple belongs on pizza", seed=0),
        provider=MockProvider(),
        suggested_tags=["texture", "tradition", "culinary-innovation"],
    )
    refs = ep.scene_manifest.character_refs
    speakers = ep.cast.all_speakers()
    assert set(refs) == {c.character_id for c in speakers}
    for c in speakers:
        ref = refs[c.character_id]
        assert ref.identity_image == f"{ref.roster_id}/identity.png"
        if c.visual_presentation.value in {"male", "female"}:
            assert ref.visual_presentation == c.visual_presentation.value

    # Same seed -> same faces; different seed -> (eventually) different faces.
    ep_same = orchestrator.run_full(
        ShowBrief(topic="Pineapple belongs on pizza", seed=0),
        provider=MockProvider(),
        suggested_tags=["texture", "tradition", "culinary-innovation"],
    )
    assert {k: v.roster_id for k, v in refs.items()} == {
        k: v.roster_id for k, v in ep_same.scene_manifest.character_refs.items()
    }


def test_every_media_prompt_anchors_the_same_studio():
    """The user-facing consistency guarantee: every image prompt (main and
    fallback, intro and speaker) embeds the canonical studio description."""
    intro_shot = {"group": "intro", "id": "intro_wide", "speakerId": "protagonist"}
    speaker_shot = {"group": "main_speaker", "id": "close", "speakerId": "protagonist"}
    for shot in (intro_shot, speaker_shot):
        assert STUDIO_SCENE in prompt_for(shot)
        assert STUDIO_SCENE in fallback_prompt_for(shot)
    for entry in characters.CHARACTER_ROSTER:
        assert STUDIO_SCENE in characters.identity_prompt_for(entry)
        assert STUDIO_SCENE in characters.identity_fallback_prompt_for(entry)


def test_frontend_studio_scene_mirrors_stay_in_sync():
    """Every JS file that embeds the studio description must carry the exact
    backend wording, so no generation path can drift into a different room."""
    index_html = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'const STUDIO_SCENE = "(?P<scene>[^"]+)";', index_html)
    assert match, "frontend/index.html must define the STUDIO_SCENE mirror"
    assert match.group("scene") == STUDIO_SCENE, (
        "frontend STUDIO_SCENE must stay byte-identical to media/studio.py"
    )

    for script in (
        "scripts/generate_realistic_references.mjs",
        "scripts/run_happyhorse_video_edit.mjs",
    ):
        text = (REPO_ROOT / "frontend" / script).read_text(encoding="utf-8")
        assert STUDIO_SCENE in text, f"{script} must embed the canonical STUDIO_SCENE"


def test_character_bank_dry_run_plans_whole_roster(tmp_path):
    settings = Settings(character_bank_dir=str(tmp_path / "characters-v1"))
    manifest = asyncio.run(characters.generate(settings, dry_run=True))
    entries = manifest["characters"]
    assert len(entries) == len(characters.CHARACTER_ROSTER)
    assert all(e["status"] == "planned" for e in entries)
    assert manifest["studio_scene"] == STUDIO_SCENE
    assert (tmp_path / "characters-v1" / "manifest.json").exists()


def test_character_bank_api_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("YVM_CHARACTER_BANK_DIR", str(tmp_path / "characters-v1"))
    client = TestClient(app)

    status = client.get("/media/character-bank/status").json()
    assert status["roster_count"] == len(characters.CHARACTER_ROSTER)
    assert status["qwen_ready"] is False

    r = client.post(
        "/media/character-bank/generate",
        json={"dry_run": True, "background": False},
    )
    assert r.status_code == 200
    assert r.json()["characters"] == len(characters.CHARACTER_ROSTER)

    # Live generation without a key must refuse cleanly.
    r = client.post("/media/character-bank/generate", json={"dry_run": False})
    assert r.status_code == 503


def test_video_edit_media_prefers_roster_identity(tmp_path, monkeypatch):
    from youvsmany.media import video_edit

    # A character bank with one generated identity.
    bank = {
        "characters": [
            {"roster_id": "vega", "identity": "vega/identity.png", "status": "generated"},
        ]
    }
    monkeypatch.setattr(video_edit, "ensure_mp4", lambda settings, clip: None)
    settings = Settings()
    segment = {
        "clip": "second_speaker/challenger_1/close/clip.webm",
        "identity": "second_speaker/challenger_1/close/starter.png",
        "starter": "second_speaker/challenger_1/close/starter.png",
        "character": "vega",
    }
    media = video_edit.build_media(settings, "https://api.example", segment, None, bank)
    assert media[0]["type"] == "video"
    assert media[1] == {
        "type": "reference_image",
        "url": "https://api.example/media/character-bank/files/vega/identity.png",
    }
    # The slot starter stays as the pose anchor.
    assert media[2]["url"].endswith("second_speaker/challenger_1/close/starter.png")

    # Unknown roster id falls back to the previous behavior.
    media = video_edit.build_media(
        settings, "https://api.example", {**segment, "character": "nobody"}, None, bank
    )
    assert all("character-bank" not in m["url"] for m in media)
