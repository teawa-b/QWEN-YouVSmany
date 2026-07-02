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
