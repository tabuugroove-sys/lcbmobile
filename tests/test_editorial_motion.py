import json
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageDraw

from src.video import editorial_motion as motion
from src.video import horizontal_news as video
from src.video import longform_beats as beats


def story():
    return {"id": "one", "artist": "João Bosco", "narration": "Notícia musical.",
            "headline": "João Bosco celebra 80 anos", "assets": [],
            "item": {"url": "https://g1.globo.com/noticia"}}


@pytest.mark.parametrize("text", [
    "E o samba tomou conta de Itajaí.",
    "João Bosco celebrou oitenta anos com uma noite de encontros no Rio de Janeiro.",
    "Pabllo Vittar mudou a direção do som, e a pergunta agora é: até onde essa nova fase pode chegar?",
    "ÁÉÍÓÚ çãê Zé Felipe & Virgínia: nova fase?",
])
def test_typography_preserves_words_accents_and_safe_area(text):
    card = motion.EditorialMotion(story(), {"text": text, "duration": 4})
    layout = card.layout
    assert " ".join(layout["lines"]) == text
    draw = ImageDraw.Draw(card.base)
    assert all(draw.textlength(line, font=layout["font"])+48 <= 1600 for line in layout["lines"])
    assert layout["top"] >= 300
    assert layout["top"] + len(layout["lines"])*layout["line_height"] <= 816
    assert card.settled_at < .8
    if len(layout["lines"]) > 1:
        assert len(layout["lines"][-1].split()) > 1


def test_motion_enters_then_leaves_words_readable_until_the_cut():
    card = motion.EditorialMotion(story(), {"text": "Uma noite de encontros no Rio de Janeiro.", "duration": 4})
    frames = [np.asarray(card.frame(t)) for t in (0, .18, 1, 2, 3.9)]
    assert np.mean(np.abs(frames[0].astype(float)-frames[1])) > 1
    assert np.mean(np.abs(frames[1].astype(float)-frames[2])) > 1
    # No continuous wobble/zoom during the reading hold; the small progress rail still moves.
    assert np.array_equal(frames[2][300:816], frames[3][300:816])
    for frame in frames:
        assert (frame[186:240, 160:1700] > 200).any()
    assert (frames[-1][300:816] > 200).sum() > 10000


def test_short_fragment_shares_clock_and_does_not_restart_animation():
    data = story()
    data["news_images"] = [{"source_page": data["item"]["url"]}]
    cues = [(0,4,"Primeira parte"), (4,8.1,"e o final da frase.")]
    plan = beats.plan_story(data, 244/30, cues)
    cards = [s for s in plan["shots"] if s["role"] == "narrative_card"]
    assert len(cards) == 2
    assert cards[1]["duration"] == pytest.approx(4/30)
    assert cards[1]["animation_offset"] == 4
    assert cards[1]["animation_duration"] == cards[0]["animation_duration"] == pytest.approx(124/30)
    assert cards[1]["animation_text"] == cards[0]["animation_text"] == "e o final da frase."
    a, b = (motion.EditorialMotion(data, s) for s in cards)
    assert a.frame(4).tobytes() == b.frame(cards[1]["animation_offset"]).tobytes()


def test_skin_version_invalidates_beats_cache(tmp_path, monkeypatch):
    (tmp_path/"alignment-one.json").write_text(json.dumps({"characters": []}))
    before = beats.input_digest([story()], tmp_path)
    monkeypatch.setattr(motion, "SKIN_VERSION", "different-layout")
    assert beats.input_digest([story()], tmp_path) != before


@pytest.mark.parametrize("text,duration", [("", 2), ("x"*5000, 2), ("Hello", 0), ("Hello", float("nan"))])
def test_invalid_cards_fail_explicitly(text, duration):
    with pytest.raises(ValueError):
        motion.EditorialMotion(story(), {"text": text, "duration": duration})


def test_encoder_preserves_exact_frames_and_reuses_complete_cache(tmp_path):
    shot = {"text": "A música continua.", "duration": .4, "animation_duration": 2}
    path = motion.render_card(story(), shot, tmp_path)
    stream = next(s for s in video.probe(path)["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"], int(stream["nb_frames"])) == (1920,1080,12)
    assert float(stream["duration"]) == pytest.approx(.4)
    assert stream["r_frame_rate"] == "30/1"
    assert not list(tmp_path.glob("*.partial.mp4"))
    modified = path.stat().st_mtime_ns
    assert motion.render_card(story(), shot, tmp_path) == path
    assert path.stat().st_mtime_ns == modified
    with pytest.raises(ValueError, match="exceeds"):
        motion.render_card(story(), {**shot,"animation_offset":1.9}, tmp_path)


def test_failed_encoder_leaves_no_cache_hit(tmp_path, monkeypatch):
    import imageio_ffmpeg

    def fail(path, *args, **kwargs):
        Path(path).write_bytes(b"incomplete encoder output")
        yield
        raise RuntimeError("encoder failed")

    monkeypatch.setattr(imageio_ffmpeg, "write_frames", fail)
    with pytest.raises(RuntimeError, match="encoder failed"):
        motion.render_card(story(), {"text":"Uma nova fase.","duration":1}, tmp_path)
    assert not list(tmp_path.glob("*.mp4"))
