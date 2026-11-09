import copy

import numpy as np
import pytest

from src.video import infographics as info
from src.video import editorial_motion as motion
from src.video import horizontal_news as video


def story():
    return {"id":"one", "artist":"Anitta", "item":{"url":"https://example.com/news"},
            "narration":"O disco tem doze faixas. Uma nova fase."}


def fact(**overrides):
    return {"value":12, "block_value":1, "unit":"faixas", "evidence_quote":"doze faixas",
            "source_page":"https://example.com/news", **overrides}


def aligned(text):
    return {"characters":list(text), "character_start_times_seconds":[i*.15 for i in range(len(text))],
            "character_end_times_seconds":[(i+1)*.15 for i in range(len(text))]}


def plan():
    return {"shots":[{"start":i*3,"duration":3,"role":"archive","asset":{"path":f"{i}.mp4"},
                       "source_start":i*10,"text":"O disco tem doze faixas.","beat_index":0}
                      for i in range(3)]}


def test_fact_only_replaces_a_shot_that_overlaps_the_spoken_evidence():
    data, montage = story(), plan()
    data["infographics"] = [fact()]
    before = copy.deepcopy(montage)
    info.apply_infographics(data, montage, aligned(data["narration"]), .05)
    event = montage["infographics"][0]
    assert event["status"] == "placed"
    index = event["shot_index"]
    shot = montage["shots"][index]
    assert min(shot["start"]+shot["duration"], event["spoken_interval"][1]) > max(shot["start"], event["spoken_interval"][0])
    assert shot["role"] == "infographic" and shot["asset"] is None
    assert shot["infographic"]["semantic_validation"] == "not_performed"
    assert [(s["start"],s["duration"]) for s in montage["shots"]] == [(s["start"],s["duration"]) for s in before["shots"]]
    assert all(s == before["shots"][i] for i,s in enumerate(montage["shots"]) if i != index)
    assert sum(montage["visual_seconds"].values()) == 9


@pytest.mark.parametrize("overrides", [
    {"value":float("nan")}, {"value":True}, {"block_value":0}, {"value":1000},
    {"unit":"views"}, {"source_page":"https://wrong.example/news"}, {"evidence_quote":"cem faixas"},
    {"evidence_quote":""}, {"approximate":"true"},
    {"value":12.25}, {"block_value":.5},
])
def test_invalid_facts_do_not_replace_existing_footage(overrides):
    data, montage = story(), plan()
    data["infographics"] = [fact(**overrides)]
    before = copy.deepcopy(montage["shots"])
    info.apply_infographics(data, montage, aligned(data["narration"]), 0)
    assert montage["shots"] == before
    assert montage["infographics"][0]["status"] == "skipped"


def test_no_implicit_statistics_and_no_reused_shot():
    data, montage = story(), plan()
    before = copy.deepcopy(montage["shots"])
    info.apply_infographics(data, montage, aligned(data["narration"]), 0)
    assert montage["shots"] == before
    data["infographics"] = [fact(), fact()]
    info.apply_infographics(data, montage, aligned(data["narration"]), 0)
    placed = [e["shot_index"] for e in montage["infographics"] if e["status"] == "placed"]
    assert len(placed) == len(set(placed)) == 1


def test_missing_alignment_keeps_footage():
    data, montage = story(), plan()
    data["infographics"] = [fact()]
    info.apply_infographics(data, montage, {}, 0)
    assert all(s["role"] == "archive" for s in montage["shots"])


def test_approximation_and_fractional_cell_preserved():
    data = story()
    data["narration"] = "Foram cerca de doze mil e quinhentas pessoas."
    proposal = fact(value=12500, block_value=1000, unit="pessoas",
                    evidence_quote="cerca de doze mil e quinhentas pessoas")
    with pytest.raises(ValueError, match="approximate"):
        info.validate_fact(proposal, data)
    proposal["approximate"] = True
    card = info.InfographicMotion(data, {"duration":3,"text":data["narration"],"infographic":proposal})
    assert card.cells == 13 and card.units == 12.5
    image = np.asarray(card.frame(2))
    # Thirteenth cell carries half a block, not a rounded-up extra thousand.
    assert tuple(image[660,1020]) == (99,216,197)
    assert tuple(image[660,1120]) == (41,43,48)
    assert info.pt_number(12.5) == "12,5"


def test_fact_animation_changes_grid_not_the_claimed_number():
    card = info.InfographicMotion(story(), {"duration":3,"text":story()["narration"],"infographic":fact()})
    first, last = (np.asarray(card.frame(t)) for t in (0,2))
    assert np.array_equal(first[300:750,160:900], last[300:750,160:900])
    assert np.mean(np.abs(first[300:780,1000:1760].astype(float)-last[300:780,1000:1760])) > 10
    assert card.settled_at <= 1


def test_actual_infographic_encode_and_versioned_cache(tmp_path, monkeypatch):
    shot = {"duration":.4,"text":story()["narration"],"role":"infographic","infographic":fact()}
    first = motion.render_card(story(), shot, tmp_path)
    stream = next(s for s in video.probe(first)["streams"] if s["codec_type"] == "video")
    assert int(stream["nb_frames"]) == 12
    monkeypatch.setattr(info, "INFOGRAPHIC_VERSION", "changed-grid")
    assert motion.render_card(story(), shot, tmp_path) != first
