import hashlib
import json

import pytest

from src.services.motion_reference_library import (
    MotionReferenceLibraryError,
    load_motion_reference_library,
    resolve_motion_reference,
    select_motion_reference,
)


def _write_library(tmp_path, assets):
    manifest = tmp_path / "motion-library.json"
    manifest.write_text(json.dumps({"version": 1, "assets": assets}), encoding="utf-8")
    return manifest


def test_motion_library_resolves_relative_paths_and_hashes_assets(tmp_path):
    clip = tmp_path / "walk.mp4"
    clip.write_bytes(b"approved-walk")
    manifest = _write_library(tmp_path, [{
        "id": "walk",
        "path": "walk.mp4",
        "tags": ["walk", "向前走"],
        "shot_roles": ["action"],
        "min_characters": 1,
        "max_characters": 1,
    }])

    assets = load_motion_reference_library(manifest)

    assert assets[0]["path"] == str(clip.resolve())
    assert assets[0]["sha256"] == hashlib.sha256(b"approved-walk").hexdigest()


def test_motion_selector_requires_tag_role_intensity_and_cast_match(tmp_path):
    walk = tmp_path / "walk.mp4"
    fight = tmp_path / "fight.mp4"
    walk.write_bytes(b"walk")
    fight.write_bytes(b"fight")
    manifest = _write_library(tmp_path, [{
        "id": "walk",
        "path": "walk.mp4",
        "tags": ["walk forward", "向前走"],
        "shot_roles": ["action"],
        "action_intensities": ["medium"],
        "min_characters": 1,
        "max_characters": 1,
        "priority": 1,
    }, {
        "id": "fight",
        "path": "fight.mp4",
        "tags": ["fight", "打斗"],
        "shot_roles": ["action"],
        "action_intensities": ["high"],
        "min_characters": 2,
        "max_characters": 2,
        "priority": 100,
    }])

    selection = resolve_motion_reference(manifest, shot_plan={
        "shot_role": "action",
        "action_intensity": "medium",
        "visible_character_count": 1,
        "director_prompt": "The heroine will walk forward toward the door",
        "shot_spec": {"character_states": [{"character_name": "heroine", "action": "向前走"}]},
    })

    assert selection is not None
    assert selection.asset_id == "walk"
    assert selection.path == str(walk.resolve())
    assert selection.matched_tags == ("walk forward", "向前走")
    assert "shot_role:action" in selection.selection_reasons
    assert "action_intensity:medium" in selection.selection_reasons


def test_motion_selector_does_not_guess_without_explicit_tag_match(tmp_path):
    clip = tmp_path / "walk.mp4"
    clip.write_bytes(b"walk")
    assets = load_motion_reference_library(_write_library(tmp_path, [{
        "id": "walk",
        "path": "walk.mp4",
        "tags": ["walk forward", "向前走"],
        "shot_roles": ["action"],
    }]))

    selection = select_motion_reference(assets, shot_plan={
        "shot_role": "action",
        "action_intensity": "medium",
        "visible_character_count": 1,
        "director_prompt": "The actor picks up a cup",
    })

    assert selection is None


def test_motion_library_rejects_missing_asset_file(tmp_path):
    manifest = _write_library(tmp_path, [{
        "id": "walk",
        "path": "missing.mp4",
        "tags": ["walk"],
    }])

    with pytest.raises(MotionReferenceLibraryError, match="does not exist"):
        load_motion_reference_library(manifest)


def test_motion_library_rejects_empty_tags(tmp_path):
    clip = tmp_path / "walk.mp4"
    clip.write_bytes(b"walk")
    manifest = _write_library(tmp_path, [{
        "id": "walk",
        "path": "walk.mp4",
        "tags": [],
    }])

    with pytest.raises(MotionReferenceLibraryError, match="tags must be a non-empty list"):
        load_motion_reference_library(manifest)
