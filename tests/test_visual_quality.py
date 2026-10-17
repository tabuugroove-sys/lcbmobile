import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.models import NewsItem
from src.storage import Store
from src.editorial.music_filter import find_music_act_query
from src.video import generator, youtube_media, mac_media
from src.video.commons_media import LicensedImage
from src.video.subject import matches_subject


@pytest.mark.parametrize('title', ['Flirting on the Red Carpet', 'Shia LaBeouf First Red Carpet Appearance'])
def test_ze_felipe_never_uses_unrelated_red_carpet(title):
    assert not matches_subject('ze felipe', title, 'Access Hollywood')


@pytest.mark.parametrize('artist,title', [('leonardo','Leonardo da Vinci painting'),('joao gomes','Joao Gomes Cravinho in 2023'),('joao gomes','Joao Gomes volante do Flamengo')])
def test_namesakes_are_not_musician_assets(artist,title):
    assert not matches_subject(artist,title)


def test_renato_is_searchable_but_coach_is_not():
    assert find_music_act_query('O que Renato Russo estaria fazendo hoje?') == 'renato russo'
    assert find_music_act_query('Flamengo: Leonardo Jardim fica sem reforcos') is None
    assert matches_subject('renato russo','Renato Russo e Legiao Urbana ao vivo')


@pytest.mark.parametrize('photos,videos',[(1,0),(2,0),(3,0),(1,1),(2,2),(8,2)])
def test_scene_plan_only_contains_existing_assets_once(photos,videos):
    plan=generator._scene_layout(photos,videos)
    assert plan[0]==('hook',0)
    seen=set()
    for kind,index in plan[1:]:
        assert index < (videos if kind=='video' else photos)
        assert (kind,index) not in seen
        seen.add((kind,index))
    assert generator._scene_layout(2,0)==[('hook',0),('photo',1)]


def test_empty_template_is_not_a_render_plan():
    with pytest.raises(RuntimeError):
        generator._scene_layout(0,0)


def test_only_successful_youtube_publications_affect_cover_history(tmp_path,monkeypatch):
    db=tmp_path/'state.db'
    store=Store(db)
    monkeypatch.setattr(generator,'settings',replace(generator.settings,db_path=db))
    first=NewsItem(source_id='test',source_name='test',category='music',url='https://example.com/first',title='Ze Felipe noticia')
    current=first.model_copy(update={'url':'https://example.com/current'})
    preview=first.model_copy(update={'url':'https://example.com/preview'})
    image=tmp_path/'first.jpg'
    Image.new('RGB',(100,100),(20,90,200)).save(image)
    asset=LicensedImage(str(image),'Ze Felipe','test','CC BY','https://license','https://source','https://image',100,100)
    for item in (first,preview):
        folder=generator._item_output_dir(item,tmp_path/'out')
        (folder/'render_manifest.json').write_text(json.dumps({'photo_assets':[asset.as_manifest()],'video_sources':[item.url]}))
    store.record_publication(first.fingerprint(),'youtube','published-id','ok')
    photos,videos=generator._recent_visual_history(current,tmp_path/'out')
    assert photos==[asset]
    assert videos=={first.url}
    assert generator._fresh_photos([asset],photos)==[]


def test_distinct_video_frame_sources_do_not_collapse_to_same_url():
    def asset(fragment):
        return LicensedImage('/missing','Renato frame','test','source','','','https://youtube.com/watch?v=one#frame='+fragment,100,100)
    assert generator._asset_source_identity(asset('0.2')) != generator._asset_source_identity(asset('0.7'))


def test_renato_and_his_band_are_not_opponents():
    item=NewsItem(source_id='test',source_name='G1',category='music',url='https://example.com/story',title='Renato Russo e companheiros da Legiao Urbana')
    def photo(title):
        return LicensedImage('/missing',title,'test','CC BY','','','',100,100)
    assert not generator._hook_pair_is_meaningful(item,photo('Renato Russo'),photo('Legiao Urbana com Wagner Moura'))


def test_insufficient_video_is_not_extended_as_frozen_frame(tmp_path,monkeypatch):
    source=SimpleNamespace(duration=5,close=Mock())
    monkeypatch.setattr(generator,'VideoFileClip',lambda *a,**k:source)
    with pytest.raises(RuntimeError,match='freeze'):
        generator._build_video_scene(media=SimpleNamespace(path='video.mp4'),overlay_path=tmp_path/'overlay.png',duration=10)
    source.close.assert_called_once()
