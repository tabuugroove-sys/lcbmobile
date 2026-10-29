import hashlib
import json
import subprocess
from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.video import horizontal_news as video


def test_opener_uses_best_reviewed_source_and_alternates_without_loops():
    assets = [{"source_page": source, "reviewed_ranges": [[0, 12]],
               "reviewed_segments": [{"start": 0, "end": 12, "score": score}]}
              for source, score in (("weak", .2), ("strong", .95), ("other", .7))]
    shots = video.plan_shots(assets, 20)
    assert shots[0]["asset"]["source_page"] == "strong"
    assert shots[0]["duration"] == 2
    assert sum(s["duration"] for s in shots) == pytest.approx(20)
    assert max(s["duration"] for s in shots) <= 4
    assert all(a["asset"]["source_page"] != b["asset"]["source_page"] for a,b in zip(shots,shots[1:]))


def test_montage_can_cut_at_a_spoken_phrase_boundary():
    assets = [{"source_page": str(i), "reviewed_ranges": [[0, 20]]} for i in range(2)]
    shots = video.plan_shots(assets, 10, cut_points=[1.8])
    assert shots[0]["duration"] == pytest.approx(1.8)


def test_ranked_segments_never_reuse_the_same_source_interval():
    assets = [{"source_page": str(i), "reviewed_ranges": [[0, 12]],
               "reviewed_segments": [{"start": a, "end": a+4, "score": score}
                                     for a,score in ((0,.2),(4,.9),(8,.5))]}
              for i in range(2)]
    shots = video.plan_shots(assets, 18)
    assert shots[0]["source_start"] == 4
    for source in ("0", "1"):
        spans = sorted((s["source_start"], s["source_start"]+s["duration"])
                       for s in shots if s["asset"]["source_page"] == source)
        assert all(b <= c+.001 for (a,b),(c,d) in zip(spans,spans[1:]))


def test_long_music_is_trimmed_to_narration_and_no_apad_is_used(tmp_path, monkeypatch):
    music = tmp_path/'music.wav'
    music.write_bytes(b'music fixture')
    (tmp_path/'voice-one.mp3').write_bytes(b'voice fixture')
    video.save(tmp_path/'alignment-one.json', {
        "characters": list('Oi.'), "character_start_times_seconds": [.2,1,10],
        "character_end_times_seconds": [.9,9,11.2],
    })
    monkeypatch.setattr(video, 'settings', replace(video.settings, background_music_path=music,
                                                  background_music_volume=.25))
    monkeypatch.setattr(video, 'duration', lambda p: 221 if p==music else 13 if p.name.startswith('voice-') else 11.1)
    def overlay(*args, **kwargs):
        path=tmp_path/'overlay.png'
        path.write_bytes(b'fixture')
        return path
    commands=[]
    def run(args, *a, **k):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, '', 'mean_volume: -13.0 dB')
    monkeypatch.setattr(video, 'overlay', overlay)
    monkeypatch.setattr(video, 'run', run)
    review=Mock()
    monkeypatch.setattr(video, 'review', review)
    stories=[{"id":"one", "artist":"Anitta", "headline":"Noticia", "assets":[
        {"sha256":str(i), "path":f'fixture-{i}.mp4', "source_page":str(i),
         "reviewed_ranges":[[0,20]], "review_policy_version":video.FOOTAGE_REVIEW_VERSION}
        for i in range(2)]}]
    video.render(stories, '2026-10-29', tmp_path)
    chapters=json.loads((tmp_path/'chapters.json').read_text())
    assert chapters[0]['narration_duration'] == pytest.approx(11.06)
    assert chapters[0]['duration'] < 13
    assert not any('apad' in arg for cmd in commands for arg in cmd)
    part=next(cmd for cmd in commands if 'atrim' in ' '.join(cmd))
    assert float(part[part.index('-t')+1]) < 13
    final=commands[-1]
    assert float(final[final.index('-t')+1]) < 13
    assert 'afade=t=out:st=' in ' '.join(final)
    review.assert_called_once()


def test_old_full_track_cache_is_not_publishable(tmp_path, monkeypatch):
    (tmp_path/'voice-one.mp3').write_bytes(b'voice')
    monkeypatch.setattr(video,'settings',replace(video.settings,background_music_volume=0))
    stories=[{'id':'one'}]
    assert not video.render_cache_current({'background_music_complete_pass':True},stories,tmp_path)
    report={'render_policy_version':video.RENDER_POLICY_VERSION,'narration_timing_passed':True,
            'footage_review_version':video.FOOTAGE_REVIEW_VERSION,
            'background_music_ratio':0,'voice_sha256':{'one':hashlib.sha256(b'voice').hexdigest()}}
    assert video.render_cache_current(report,stories,tmp_path)
    (tmp_path/'voice-one.mp3').write_bytes(b'new voice')
    assert not video.render_cache_current(report,stories,tmp_path)


def test_review_rejects_a_music_tail_after_narration(tmp_path, monkeypatch):
    monkeypatch.setattr(video,'probe',lambda p:{'streams':[{'codec_type':'video','width':1920,'height':1080}]})
    monkeypatch.setattr(video,'duration',lambda p:40)
    video.save(tmp_path/'chapters.json',[{'start':0,'duration':40,'narration_duration':30}])
    with pytest.raises(RuntimeError,match='extends beyond narration'):
        video.review(tmp_path/'video.mp4',[],[],tmp_path)
