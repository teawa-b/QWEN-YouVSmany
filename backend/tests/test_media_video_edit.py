import asyncio
import json

from fastapi.testclient import TestClient

from youvsmany.api.main import app
from youvsmany.config import Settings
from youvsmany.media import video_edit


def make_settings(tmp_path, **overrides):
    defaults = dict(
        qwen_dashscope_api_key="test-key",
        video_out_dir=str(tmp_path / "videos"),
        reference_mp4_dir=str(tmp_path / "reference-mp4"),
        realistic_ref_dir=str(tmp_path / "realistic-v1"),
    )
    defaults.update(overrides)
    return Settings(**defaults)


def sample_segment(index=0):
    return {
        "segment_id": f"seg_{index:03d}",
        "speaker_id": "protagonist",
        "prompt": "Transform this clip into a realistic debate shot.",
        "clip": "main_speaker/protagonist/close/clip.webm",
        "identity": "main_speaker/protagonist/close/starter.png",
        "starter": "main_speaker/protagonist/close/starter.png",
    }


def test_health_reports_video_fields():
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["video_model"] == "happyhorse-1.0-video-edit"
    assert "ffmpeg" in body


def test_video_edit_status_endpoint():
    client = TestClient(app)
    body = client.get("/media/video-edit/status").json()
    assert body["model"] == "happyhorse-1.0-video-edit"
    assert body["files_url"] == "/media/video-edit/files/"


def test_generate_requires_key_when_not_dry_run(tmp_path):
    settings = make_settings(tmp_path, qwen_dashscope_api_key="")
    try:
        asyncio.run(
            video_edit.generate(
                settings, base_url="https://api.example.com", segments=[sample_segment()]
            )
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "DASHSCOPE_API_KEY" in str(exc)


def test_dry_run_builds_public_media_urls(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(video_edit, "ensure_mp4", lambda s, rel: tmp_path / "clip.mp4")

    manifest = asyncio.run(
        video_edit.generate(
            settings,
            base_url="https://api.example.com",
            segments=[sample_segment()],
            dry_run=True,
        )
    )

    entry = manifest["segments"][0]
    assert entry["status"] == "planned"
    media = entry["media"]
    assert media[0]["type"] == "video"
    assert media[0]["url"] == (
        "https://api.example.com/media/reference-mp4/files/"
        "main_speaker/protagonist/close/clip.mp4"
    )
    assert media[1]["type"] == "reference_image"
    assert media[1]["url"] in {
        "https://api.example.com/media/reference/files/main_speaker/protagonist/close/starter.png",
        "https://api.example.com/media/realistic-refs/files/main_speaker/protagonist/close/realistic.png",
    }
    assert (tmp_path / "videos" / "manifest.json").exists()


def test_dry_run_prefers_realistic_identity_when_bank_exists(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(video_edit, "ensure_mp4", lambda s, rel: tmp_path / "clip.mp4")
    realistic_dir = tmp_path / "realistic-v1"
    realistic_dir.mkdir(parents=True)
    (realistic_dir / "manifest.json").write_text(
        json.dumps(
            {
                "dry_run": False,
                "shots": [
                    {
                        "starter": "main_speaker/protagonist/close/starter.png",
                        "realistic": "main_speaker/protagonist/close/realistic.png",
                        "status": "generated",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = asyncio.run(
        video_edit.generate(
            settings,
            base_url="https://api.example.com",
            segments=[sample_segment()],
            dry_run=True,
        )
    )

    media = manifest["segments"][0]["media"]
    assert media[1]["url"] == (
        "https://api.example.com/media/realistic-refs/files/"
        "main_speaker/protagonist/close/realistic.png"
    )


def test_failed_segment_recorded_and_run_continues(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(video_edit, "ensure_mp4", lambda s, rel: tmp_path / "clip.mp4")
    monkeypatch.setattr(video_edit, "ffmpeg_path", lambda: "ffmpeg")

    async def failing_create(client, settings, media, prompt, resolution):
        raise video_edit.QwenRequestError(400, "InvalidParameter", "bad media")

    async def fake_poll(client, settings, task_id):
        raise AssertionError("poll should not run when create fails")

    monkeypatch.setattr(video_edit, "create_task", failing_create)
    monkeypatch.setattr(video_edit, "poll_task", fake_poll)
    monkeypatch.setattr(video_edit, "stitch", lambda settings, entries, out_dir: None)

    manifest = asyncio.run(
        video_edit.generate(
            settings,
            base_url="https://api.example.com",
            segments=[sample_segment(0), sample_segment(1)],
        )
    )

    statuses = [e["status"] for e in manifest["segments"]]
    assert statuses == ["failed", "failed"]
    assert manifest["failed_count"] == 2
    assert "InvalidParameter" in manifest["segments"][0]["error"]


def test_successful_segment_downloads_video(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(video_edit, "ensure_mp4", lambda s, rel: tmp_path / "clip.mp4")
    monkeypatch.setattr(video_edit, "ffmpeg_path", lambda: "ffmpeg")

    async def fake_create(client, settings, media, prompt, resolution):
        return "task-123"

    async def fake_poll(client, settings, task_id):
        return {"output": {"task_status": "SUCCEEDED", "video_url": "https://example.com/v.mp4"}}

    async def fake_download(client, url, file):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"mp4")

    monkeypatch.setattr(video_edit, "create_task", fake_create)
    monkeypatch.setattr(video_edit, "poll_task", fake_poll)
    monkeypatch.setattr(video_edit, "download", fake_download)
    monkeypatch.setattr(video_edit, "stitch", lambda settings, entries, out_dir: "conversation.mp4")

    manifest = asyncio.run(
        video_edit.generate(
            settings,
            base_url="https://api.example.com",
            segments=[sample_segment()],
        )
    )

    entry = manifest["segments"][0]
    assert entry["status"] == "generated"
    assert entry["task_id"] == "task-123"
    assert (tmp_path / "videos" / entry["video"]).exists()
    assert manifest["conversation"] == "conversation.mp4"


def test_stitch_writes_concat_paths_relative_to_work_dir(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    out_dir = tmp_path / "videos"
    segment = out_dir / "segments" / "000_seg_00.mp4"
    segment.parent.mkdir(parents=True)
    segment.write_bytes(b"mp4")
    concat_files = []

    def fake_run(cmd, check, capture_output):
        if "-f" in cmd and "concat" in cmd:
            list_file = video_edit.Path(cmd[cmd.index("-i") + 1])
            concat_files.append(list_file.read_text(encoding="utf-8"))
        return video_edit.subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(video_edit, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(video_edit.subprocess, "run", fake_run)

    result = video_edit.stitch(
        settings,
        [{"status": "generated", "video": "segments/000_seg_00.mp4"}],
        out_dir,
    )

    assert result == "conversation.mp4"
    assert concat_files == ["file 'part_000.mp4'\n"]


def test_generate_endpoint_dry_run_returns_job(monkeypatch, tmp_path):
    monkeypatch.setenv("YVM_VIDEO_OUT_DIR", str(tmp_path / "videos"))
    monkeypatch.setenv("YVM_REFERENCE_MP4_DIR", str(tmp_path / "reference-mp4"))
    monkeypatch.setattr(video_edit, "ensure_mp4", lambda s, rel: tmp_path / "clip.mp4")
    client = TestClient(app)

    response = client.post(
        "/media/video-edit/generate",
        json={"segments": [sample_segment()], "dry_run": True, "background": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["segments"] == 1
