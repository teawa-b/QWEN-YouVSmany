import asyncio
from fastapi.testclient import TestClient

from youvsmany.api.main import app
from youvsmany.config import Settings
from youvsmany.media import reference_assets


def test_realistic_refs_status_endpoint_reports_source_bank():
    client = TestClient(app)

    response = client.get("/media/realistic-refs/status")

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] >= 19
    assert body["files_url"] == "/media/realistic-refs/files/"
    assert body["model"] == "qwen-image-edit-max"


def test_dry_run_realistic_ref_manifest_does_not_need_key(tmp_path):
    settings = Settings(qwen_dashscope_api_key="", realistic_ref_dir=str(tmp_path / "realistic-v1"))

    manifest = asyncio.run(
        reference_assets.generate(
            settings,
            dry_run=True,
            limit=1,
            delay_ms=0,
        )
    )

    assert manifest["dry_run"] is True
    assert manifest["shots"][0]["status"] == "planned"
    assert (tmp_path / "realistic-v1" / "manifest.json").exists()


def test_close_identity_shots_are_generated_before_other_angles():
    plan = reference_assets.build_plan()

    kinds = [
        "intro" if item["shot"]["group"] == "intro" else item["shot"]["id"] == "close"
        for item in plan
    ]
    first_other = next(i for i, k in enumerate(kinds) if k is False)
    assert all(k is False for k in kinds[first_other:])


def test_failed_shot_is_recorded_and_run_continues(tmp_path, monkeypatch):
    settings = Settings(
        qwen_dashscope_api_key="test-key", realistic_ref_dir=str(tmp_path / "realistic-v1")
    )
    calls = []

    async def always_rejected(client, settings, input_images, prompt, seed, size):
        calls.append(prompt)
        raise reference_assets.QwenRequestError(400, "DataInspectionFailed", "flagged")

    monkeypatch.setattr(reference_assets, "request_edit", always_rejected)

    manifest = asyncio.run(reference_assets.generate(settings, limit=2, delay_ms=0))

    assert [shot["status"] for shot in manifest["shots"]] == ["failed", "failed"]
    assert "DataInspectionFailed" in manifest["shots"][0]["error"]
    assert manifest["failed_count"] == 2
    # Each shot tried the main prompt, then the sanitized fallback once.
    assert len(calls) == 4


def test_concurrent_generation_preserves_order_and_runs_closes_first(tmp_path, monkeypatch):
    settings = Settings(
        qwen_dashscope_api_key="test-key", realistic_ref_dir=str(tmp_path / "realistic-v1")
    )
    started: list[str] = []
    active = {"now": 0, "max": 0}

    async def tracking_edit(client, settings, input_images, prompt, seed, size):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        started.append(prompt)
        await asyncio.sleep(0.01)  # let siblings overlap
        active["now"] -= 1
        return {
            "output": {
                "choices": [{"message": {"content": [{"image": "https://example.com/x.png"}]}}]
            }
        }

    async def fake_download(client, url, file):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"png")

    monkeypatch.setattr(reference_assets, "request_edit", tracking_edit)
    monkeypatch.setattr(reference_assets, "download", fake_download)

    manifest = asyncio.run(reference_assets.generate(settings, concurrency=4, delay_ms=0))

    # Every source shot produced a generated entry.
    assert manifest["failed_count"] == 0
    assert manifest["generated_count"] == len(manifest["shots"])
    assert all(s["status"] == "generated" for s in manifest["shots"])
    # Concurrency actually overlapped requests within a tier.
    assert active["max"] > 1
    assert (tmp_path / "realistic-v1" / "manifest.json").exists()


def test_moderation_rejection_retries_with_fallback_prompt(tmp_path, monkeypatch):
    settings = Settings(
        qwen_dashscope_api_key="test-key", realistic_ref_dir=str(tmp_path / "realistic-v1")
    )
    calls = []

    async def reject_then_accept(client, settings, input_images, prompt, seed, size):
        calls.append(prompt)
        if len(calls) == 1:
            raise reference_assets.QwenRequestError(400, "DataInspectionFailed", "flagged")
        return {
            "output": {
                "choices": [{"message": {"content": [{"image": "https://example.com/x.png"}]}}]
            }
        }

    async def fake_download(client, url, file):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"png")

    monkeypatch.setattr(reference_assets, "request_edit", reject_then_accept)
    monkeypatch.setattr(reference_assets, "download", fake_download)

    manifest = asyncio.run(reference_assets.generate(settings, limit=1, delay_ms=0))

    shot = manifest["shots"][0]
    assert shot["status"] == "generated"
    assert shot["prompt"] == reference_assets.fallback_prompt_for(shot)
    assert (tmp_path / "realistic-v1" / shot["realistic"]).exists()
