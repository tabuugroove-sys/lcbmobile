from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from src.analytics.winner_insights import build_insights, topic_bonus, write_insights
from src.analytics.youtube_metrics import _refresh_channel_history
from src.analytics.scorer import select_best_candidates
from src.models import NewsItem
from src.storage import Store

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def example(index, title='Cantora anuncia show', views=100, subscribers=1, age=30):
    return dict(video_id=str(index), fingerprint=f'fp-{index}', title=title,
                view_count=views, subscribers_gained=subscribers, content_format='short',
                analytics_collected_at=NOW.isoformat(),
                context={'published_at': (NOW - timedelta(days=age)).isoformat(), 'duration_seconds': 40})


class WinnerInsightsTests(TestCase):
    def test_selection_records_bounded_effect_and_preserves_eligibility(self):
        store = Mock()
        rows = [example(i, 'Cantora em luto', 10_000, 30) for i in range(6)]
        rows += [example(i) for i in range(6, 12)]
        for row in rows:
            row['analytics_collected_at'] = datetime.now(timezone.utc).isoformat()
        store.analytics_examples.return_value = rows
        candidate = NewsItem(source_id='test', source_name='Test', category='musica',
                             url='https://example.com/new', title='Anitta em luto', summary='')
        self.assertEqual(select_best_candidates([candidate], store, limit=1, stage='test',
                                               eligibility=lambda _: False), [])
        score = store.record_candidate_scores.call_args.kwargs['scores'][0]
        self.assertIn('topic_lift=0.60', score[2])
        self.assertIn('audience_n=12', score[2])
        select_best_candidates([candidate], store, limit=1, stage='daily_multinews')
        long_score = store.record_candidate_scores.call_args.kwargs['scores'][0]
        self.assertIn('topic_lift=0.00', long_score[2])
        self.assertAlmostEqual(score[1]-long_score[1], .48)

    def test_legacy_examples_are_not_invented_training_data(self):
        self.assertEqual(build_insights([{'title': 'foo'}], now=NOW)['training_count'], 0)

    def test_single_hit_has_no_learned_bonus(self):
        rows = [example(0, 'Cantora em luto', 100_000, 150)] + [example(i) for i in range(1, 8)]
        profile = build_insights(rows, now=NOW)
        self.assertEqual(topic_bonus(profile, {'loss_mourning'}), 0)

    def test_compare_controls_shrink_and_bound_bonus(self):
        rows = [example(i, 'Cantora em luto', 100_000, 150) for i in range(10)]
        rows += [example(i, views=2, subscribers=0) for i in range(10, 20)]
        profile = build_insights(rows, now=NOW)
        bonus = topic_bonus(profile, {'loss_mourning'})
        self.assertGreater(bonus, 0)
        self.assertLessEqual(bonus, .6)
        self.assertEqual(profile['topics']['loss_mourning']['control_size'], 10)
        rows[0]['like_count'], rows[0]['comment_count'] = 999999, 999999
        self.assertEqual(build_insights(rows, now=NOW), profile)

    def test_negative_evidence_reduces_topic_bonus(self):
        rows = [example(i, 'Cantora em luto', 1, 0) for i in range(5)]
        rows += [example(i, views=10000, subscribers=30) for i in range(5, 10)]
        self.assertLess(topic_bonus(build_insights(rows, now=NOW), {'loss_mourning'}), 0)

    def test_excludes_young_stale_long_unknown_and_duplicates(self):
        rows = [example(i) for i in range(6)]
        young, stale, long, unknown = example(20, age=1), example(21), example(22), example(23)
        stale['analytics_collected_at'] = (NOW - timedelta(days=8)).isoformat()
        long['content_format'], unknown['content_format'] = 'long', None
        profile = build_insights(rows + [rows[0], young, stale, long, unknown], now=NOW)
        self.assertEqual(profile['training_count'], 6)
        self.assertEqual(profile['shorts_count'], 8)

    def test_age_cohorts_do_not_reward_old_exposure_alone(self):
        rows = [example(i, 'Cantora em luto', 10_000, 100, age=300) for i in range(6)]
        rows += [example(i, views=100, subscribers=1, age=5) for i in range(6, 12)]
        self.assertEqual(topic_bonus(build_insights(rows, now=NOW), {'loss_mourning'}), 0)

    def test_top_sorted_by_views_and_unknown_visuals_not_static(self):
        profile = build_insights([example(1), example(2, views=300, subscribers=6)], now=NOW)
        self.assertEqual(profile['top_videos'][0]['video_id'], '2')
        self.assertEqual(profile['top_videos'][0]['subscribers_per_1000_views'], 20)
        self.assertEqual(profile['top_videos'][0]['visual_evidence'], {'status': 'unknown'})

    def test_manifest_is_observational_not_a_topic_bonus(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'fp-1').mkdir()
            (root / 'fp-1' / 'render_manifest.json').write_text(json.dumps({
                'scene_count': 10, 'duration_seconds': 40, 'licensed_video_count': 1,
                'licensed_photo_count': 3, 'style': 'mixed'}))
            profile = build_insights([example(i) for i in range(6)], now=NOW, output_dir=root)
        self.assertEqual(profile['visual_groups']['with_video']['n'], 1)
        self.assertEqual(profile['top_videos'][1]['visual_evidence']['mean_scene_seconds'], 4)

    def test_store_retains_context_and_deduplicates_publications(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.db')
            for fingerprint in ['a', 'b']:
                store.record_publication(fingerprint, 'youtube', 'video-a', 'ok')
            store.record_youtube_growth_metrics(fingerprint='a', video_id='video-a', view_count=12,
                                               subscribers_gained=2, title='Headline', content_format='short')
            store.record_youtube_context('video-a', {'duration_seconds': 30})
            rows = store.analytics_examples(None)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['context']['duration_seconds'], 30)
            path = write_insights(store, Path(tmp))
            self.assertEqual(json.loads(path.read_text())['top_videos'][0]['views'], 12)
            self.assertTrue(store.analytics_refresh_due('test', 6))
            store.mark_analytics_refreshed('test')
            self.assertFalse(store.analytics_refresh_due('test', 6))


class FullHistoryTests(TestCase):
    def services(self, count=205):
        data, analytics = Mock(), Mock()
        data.channels().list().execute.return_value = {'items': [{
            'id': 'UC-TFUUc4YHleNoIFXBVaj7A',
            'contentDetails': {'relatedPlaylists': {'uploads': 'uploads-id'}}}]}
        pages = []
        for start in range(0, count, 50):
            page = {'items': [{'contentDetails': {'videoId': str(i)}} for i in range(start, min(count, start+50))]}
            if start+50 < count:
                page['nextPageToken'] = str(start+50)
            pages.append(page)
        data.playlistItems().list().execute.side_effect = pages

        def query(**kwargs):
            ids = kwargs['filters'].removeprefix('video==').split(',')
            result = Mock()
            # A missing row must not become a synthetic zero-view example.
            result.execute.return_value = {'columnHeaders': [{'name': k} for k in ['video', 'views', 'subscribersGained']],
                                          'rows': [[i, 100, 1] for i in ids if i != '1']}
            return result
        analytics.reports().query.side_effect = query
        return data, analytics

    def test_all_uploads_over_200_and_missing_metrics_not_zero(self):
        data, analytics = self.services()
        store = Mock()
        with patch('src.analytics.youtube_metrics._video_metadata', return_value={}), \
             patch('src.analytics.winner_insights.write_insights'):
            self.assertEqual(_refresh_channel_history(store, analytics, data), 204)
        self.assertEqual(analytics.reports().query.call_count, 5)
        self.assertEqual(store.record_youtube_growth_metrics.call_count, 204)
        self.assertNotIn('1', [c.kwargs['video_id'] for c in store.record_youtube_growth_metrics.call_args_list])
        store.mark_analytics_refreshed.assert_called_once_with('channel_history_v2')

    def test_wrong_channel_stops_before_read_or_write(self):
        data, analytics = self.services()
        data.channels().list().execute.return_value['items'][0]['id'] = 'wrong'
        store = Mock()
        with self.assertRaisesRegex(RuntimeError, 'different channel'):
            _refresh_channel_history(store, analytics, data)
        store.record_youtube_growth_metrics.assert_not_called()

    def test_partial_api_failure_never_marks_full_refresh_complete(self):
        data, analytics = self.services()
        analytics.reports().query.side_effect = RuntimeError('API unavailable')
        store = Mock()
        with self.assertRaises(RuntimeError):
            _refresh_channel_history(store, analytics, data)
        store.record_youtube_growth_metrics.assert_not_called()
        store.mark_analytics_refreshed.assert_not_called()

    def test_repeating_page_token_stops(self):
        data, analytics = self.services()
        data.playlistItems().list().execute.side_effect = [
            {'items': [], 'nextPageToken': 'same'}, {'items': [], 'nextPageToken': 'same'}]
        with self.assertRaisesRegex(RuntimeError, 'pagination'):
            _refresh_channel_history(Mock(), analytics, data)
