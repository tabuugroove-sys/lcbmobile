import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.responder.full_channel import pages, replies, respond_all
from src.responder.store import CommentStore
from src.responder import reply_writer


def comment(cid, author='viewer', parent=None):
    snippet = dict(authorChannelId={'value': author}, authorDisplayName='@viewer',
                   textOriginal='Amei demais!', publishedAt='2026-01-01T00:00:00Z')
    if parent:
        snippet['parentId'] = parent
    return dict(id=cid, snippet=snippet)


def thread(cid, children=None):
    children = children or []
    return dict(id='thread-'+cid, snippet=dict(topLevelComment=comment(cid),
        videoId='old-video', channelId='ours', totalReplyCount=len(children)),
        replies=dict(comments=children))


class FullCommentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CommentStore(Path(self.temp.name)/'comments.db')
        self.service = Mock()
        self.service.videos().list().execute.return_value = {
            'items': [dict(snippet=dict(channelId='ours', title='Show musical'))]}
        self.service.comments().insert().execute.return_value = {'id': 'receipt'}
        self.service.comments().insert.reset_mock()
        self.env = patch.dict(os.environ, COMMENT_MAX_PER_RUN='0', COMMENT_REPLY_DELAY_SECONDS='0')
        self.env.start()
        self.addCleanup(self.env.stop)

    @patch('src.responder.full_channel.generate_reply', return_value={'should_reply': True, 'reply': 'Que energia boa!', 'reason': 'positive'})
    def test_second_page_old_video_and_nested_reply_are_processed(self, generate):
        a, b = thread('a'), thread('b', [comment('child', parent='b')])
        def listing(**args):
            if 'id' in args:
                return SimpleNamespace(execute=lambda: {'items': [a if args['id']=='thread-a' else b]})
            return SimpleNamespace(execute=lambda: {'items': [b]} if args.get('pageToken') else {'items': [a], 'nextPageToken': 'older'})
        self.service.commentThreads().list.side_effect = listing
        stats = respond_all(self.service, self.store, 'ours')
        self.assertEqual(stats['replied'], 3)
        self.assertEqual(stats['queued'], 0)
        self.assertTrue(self.store.is_handled('child'))
        self.assertEqual(self.service.comments().insert.call_args.kwargs['body']['snippet']['parentId'], 'b')
        self.assertTrue(self.service.comments().insert.call_args.kwargs['body']['snippet']['textOriginal'].startswith('@viewer '))

    @patch('src.responder.full_channel.generate_reply', return_value={'should_reply': False, 'reply': '', 'reason': 'minimax error: failed'})
    def test_provider_failure_keeps_queue(self, generate):
        self.service.commentThreads().list().execute.return_value = {'items': [thread('a')]}
        stats = respond_all(self.service, self.store, 'ours')
        self.assertEqual(stats['errors'], 1)
        self.assertFalse(self.store.is_handled('a'))
        self.assertEqual(stats['queued'], 1)
        self.service.comments().insert.assert_not_called()

    @patch('src.responder.full_channel.generate_reply')
    def test_all_remote_reply_pages_prevent_duplicate_after_migration(self, generate):
        t = thread('a')
        t['snippet']['totalReplyCount'] = 2
        self.service.commentThreads().list().execute.return_value = {'items': [t]}
        self.service.comments().list().execute.side_effect = [
            {'items': [comment('other')], 'nextPageToken': 'next'},
            {'items': [comment('ours-reply', 'ours', 'a')]}]
        stats = respond_all(self.service, self.store, 'ours')
        self.assertEqual(stats['replied'], 0)
        generate.assert_not_called()
        self.assertTrue(self.store.is_handled('a'))

    @patch('src.responder.full_channel.generate_reply', return_value={'should_reply': True, 'reply': 'Que bom!', 'reason': 'positive'})
    def test_dry_run_has_no_delivery_marks(self, generate):
        self.service.commentThreads().list().execute.return_value = {'items': [thread('a')]}
        stats = respond_all(self.service, self.store, 'ours', dry_run=True)
        self.assertEqual(stats['replied'], 1)
        self.assertFalse(self.store.is_handled('a'))
        self.service.comments().insert.assert_not_called()

    def test_queue_survives_restart_and_keeps_fifo_on_rescan(self):
        for cid in ['a', 'b', 'a']:
            self.store.enqueue(dict(comment_id=cid,video_id='v',parent_id=cid,thread_id='t',author='u',text='hi',context=''))
        restarted = CommentStore(self.store.db_path)
        self.assertEqual([r['comment_id'] for r in restarted.pending()], ['a','b'])

    @patch('src.responder.full_channel.generate_reply', return_value={'should_reply': True, 'reply': 'Que bom!', 'reason': 'positive'})
    def test_batch_limit_keeps_backlog_not_daily_cap(self, generate):
        a,b = thread('a'),thread('b')
        def listing(**args):
            items = [a,b] if 'id' not in args else [a if args['id']=='thread-a' else b]
            return SimpleNamespace(execute=lambda: {'items':items})
        self.service.commentThreads().list.side_effect = listing
        with patch.dict(os.environ, COMMENT_MAX_PER_RUN='1', COMMENT_DAILY_CAP='1'):
            first = respond_all(self.service, self.store, 'ours')
            second = respond_all(self.service, self.store, 'ours')
        self.assertEqual(first['queued'],1)
        self.assertEqual(second['replied'],1)
        self.assertEqual(second['queued'],0)

    @patch('src.responder.full_channel.generate_reply')
    def test_wrong_channel_is_excluded(self, generate):
        t=thread('a')
        t['snippet']['channelId']='someone-else'
        self.service.commentThreads().list().execute.return_value={'items':[t]}
        stats=respond_all(self.service,self.store,'ours')
        self.assertEqual(stats['queued'],0)
        generate.assert_not_called()

    @patch('src.responder.reply_writer._via_minimax', return_value={'should_reply': True, 'reply': 'Amei essa energia!', 'reason': 'joy'})
    @patch('src.responder.reply_writer._via_anthropic')
    def test_minimax_is_exclusive_provider(self, old, minimax):
        with patch.dict(os.environ, COMMENT_REPLY_PROVIDER='minimax'):
            result = reply_writer.generate_reply('Show', 'Amei')
        self.assertTrue(result['should_reply'])
        old.assert_not_called()

    def test_malformed_model_decision_is_not_coerced_to_true(self):
        with self.assertRaises(ValueError):
            reply_writer._coerce({'should_reply': 'false', 'reply': 'wrong'})

    @patch('src.responder.reply_writer.anthropic.Anthropic')
    def test_minimax_uses_official_endpoint_and_complete_text_only(self, client):
        api = client.return_value.__enter__.return_value
        api.messages.create.return_value = SimpleNamespace(stop_reason='end_turn',content=[
            SimpleNamespace(type='thinking'), SimpleNamespace(type='text',text='{"should_reply":true,"reply":"Que alegria!","reason":"positive"}')])
        with patch.dict(os.environ, MINIMAX_API_KEY='test-only'):
            payload = reply_writer._via_minimax('Titulo','Amei','Autor')
        self.assertEqual(payload['reply'], 'Que alegria!')
        self.assertEqual(client.call_args.kwargs['base_url'], 'https://api.minimax.io/anthropic')
        self.assertGreater(api.messages.create.call_args.kwargs['max_tokens'], 300)


if __name__ == '__main__':
    unittest.main()
