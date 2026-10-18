from PIL import Image

from src.services.cover_quality_audit import audit_cover


def test_cover_quality_audit_accepts_readable_vertical_cover(tmp_path):
    path = tmp_path / "cover.jpg"
    image = Image.new("RGB", (768, 1344), (40, 100, 180))
    image.paste((220, 180, 80), (250, 300, 520, 1050))
    image.save(path)

    report = audit_cover(path, expected_width=768, expected_height=1344)

    assert report["status"] == "passed"
    assert report["width"] == 768


def test_cover_quality_audit_flags_geometry_and_low_contrast(tmp_path):
    path = tmp_path / "cover.jpg"
    Image.new("RGB", (100, 100), (120, 120, 120)).save(path)

    report = audit_cover(path, expected_width=768, expected_height=1344)

    assert report["status"] == "needs_review"
    assert {item["code"] for item in report["issues"]} == {
        "cover_geometry_mismatch", "cover_low_contrast",
    }


def test_cover_quality_audit_reports_missing_cover(tmp_path):
    report = audit_cover(tmp_path / "missing.jpg", expected_width=768, expected_height=1344)

    assert report["status"] == "unavailable"
