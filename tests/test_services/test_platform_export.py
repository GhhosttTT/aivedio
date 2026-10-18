import json

import pytest

from src.services.platform_export import PlatformExportError, export_platform_video


def test_platform_export_is_cached_and_has_contract(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    first = export_platform_video(source, tmp_path, "douyin")
    second = export_platform_video(source, tmp_path, "douyin")

    assert first["width"] == 1080
    assert first["height"] == 1920
    assert second["output_path"] == first["output_path"]
    assert len(calls) == 1
    assert json.loads((tmp_path / "exports" / "douyin.json").read_text())["preset"] == "douyin"


def test_platform_export_rejects_unknown_preset(tmp_path):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    with pytest.raises(PlatformExportError, match="Unknown"):
        export_platform_video(source, tmp_path, "unknown")
