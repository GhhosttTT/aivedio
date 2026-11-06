from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.services.generation_review import GenerationReviewService, IdentityObservation, ReviewError


def test_identity_observation_uses_canonical_expected_fields(tmp_path):
    image = tmp_path / "reference.png"
    Image.new("RGB", (64, 64), "blue").save(image)
    reviewer = Mock()
    reviewer.evaluate.return_value = IdentityObservation(
        observed_spec={"eyes": "amber eyes", "unknown": "ignored"},
        evidence="visible amber eyes and clear hairline",
    )

    result = GenerationReviewService(reviewer).observe_character_identity(
        image, {"eyes": "amber eyes", "hair": "black bob"},
    )

    assert result["observed_spec"] == {"eyes": "amber eyes"}
    payload = reviewer.evaluate.call_args.args[1]
    assert payload["expected_identity"] == {"eyes": "amber eyes", "hair": "black bob"}
    assert reviewer.evaluate.call_args.args[3] == [image]


def test_identity_observation_rejects_missing_image(tmp_path):
    with pytest.raises(ReviewError, match="does not exist"):
        GenerationReviewService(Mock()).observe_character_identity(
            Path(tmp_path / "missing.png"), {"eyes": "amber eyes"},
        )
