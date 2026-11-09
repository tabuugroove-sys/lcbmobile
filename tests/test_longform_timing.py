import math

import pytest

from src.video.horizontal_news import FPS, narration_frames
from src.video import longform_beats


@pytest.mark.parametrize("spans", [
    [41.414, 23.593, 25.846, 28.179],
    [10.017] * 5,
    [10.014] * 5,
    [3.01, 8.023, 14.001, 29.029, 30.015],
])
def test_chapters_share_one_frame_clock(spans):
    elapsed, frames = 0.0, 0
    for span in spans:
        count = narration_frames(elapsed, span)
        assert abs(count / FPS - span) < 1 / FPS
        frames += count
        elapsed += span
        assert frames == round(elapsed * FPS)
    assert abs(frames / FPS - sum(spans)) <= .5 / FPS


def test_previous_per_chapter_rounding_accumulated_two_frames():
    spans = [41.414, 23.593, 25.846, 28.179]
    assert sum(math.ceil(span * FPS) for span in spans) - round(sum(spans) * FPS) == 2


@pytest.mark.parametrize("elapsed,span", [(-1, 1), (0, 0), (0, .001), (0, float("nan")), (float("inf"), 1)])
def test_invalid_frame_interval_is_rejected(elapsed, span):
    with pytest.raises(ValueError):
        narration_frames(elapsed, span)


def test_timing_policy_invalidates_final_render_cache(tmp_path, monkeypatch):
    before = longform_beats.input_digest([], tmp_path)
    monkeypatch.setattr(longform_beats, "TIMING_VERSION", 999)
    assert before != longform_beats.input_digest([], tmp_path)
