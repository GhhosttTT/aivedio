from scripts.ocr_subtitles import merge_frame_results


def test_merge_frame_results_combines_repeated_subtitles():
    segments = merge_frame_results(
        [
            (0.0, "wake up", 0.9),
            (0.5, "wake up", 0.91),
            (1.0, "", None),
            (2.0, "where am i", 0.88),
        ],
        frame_duration=0.5,
        merge_gap=0.85,
        min_duration=0.3,
    )

    assert len(segments) == 2
    assert segments[0].start == 0.0
    assert segments[0].end == 1.0
    assert segments[0].text == "wake up"
    assert segments[0].confidence == 0.91
    assert segments[1].start == 2.0
    assert segments[1].end == 2.5


def test_merge_frame_results_drops_too_short_segments():
    segments = merge_frame_results(
        [(0.0, "noise", 0.7)],
        frame_duration=0.2,
        merge_gap=0.5,
        min_duration=0.35,
    )

    assert segments == []
