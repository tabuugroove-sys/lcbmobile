"""Persistent full-channel comment queue; no age or video-count cutoff."""
from __future__ import annotations

import logging
import os
import time

from googleapiclient.errors import HttpError

from .reply_writer import generate_reply

log = logging.getLogger(__name__)


def pages(resource, **kwargs):
    token = None
    while True:
        response = resource.list(**kwargs, pageToken=token).execute()
        yield response.get('items', [])
        token = response.get('nextPageToken')
        if not token:
            return


def replies(service, thread):
    inline = thread.get('replies', {}).get('comments', [])
    total = thread['snippet'].get('totalReplyCount', 0)
    if total <= len(inline):
        return inline
    return [c for page in pages(service.comments(), part='snippet',
        parentId=thread['snippet']['topLevelComment']['id'], maxResults=100,
        textFormat='plainText') for c in page]


def author_id(comment):
    return (comment['snippet'].get('authorChannelId') or {}).get('value')


def answered(comment, thread_replies, channel):
    """A top-level reply or an explicit addressed reply is remote delivery evidence."""
    for reply in thread_replies:
        if author_id(reply) != channel:
            continue
        if not comment['snippet'].get('parentId'):
            return True
        snip = reply['snippet']
        handle = comment['snippet'].get('authorDisplayName', '').strip()
        if (handle and snip.get('textOriginal', '').startswith(handle + ' ')
                and snip.get('publishedAt', '') >= comment['snippet'].get('publishedAt', '')):
            return True
    return False


def respond_all(service, store, channel, *, dry_run=False):
    stats = dict(videos=0, scanned=0, replied=0, skipped=0, errors=0, queued=0)
    videos = set()
    for page in pages(service.commentThreads(), part='snippet,replies',
            allThreadsRelatedToChannelId=channel, maxResults=100,
            order='time', textFormat='plainText', moderationStatus='published'):
        for thread in page:
            top = thread['snippet']['topLevelComment']
            video = thread['snippet'].get('videoId')
            if not video or thread['snippet'].get('channelId') != channel:
                continue
            videos.add(video)
            children = replies(service, thread)
            for comment in [top, *children]:
                if author_id(comment) == channel or store.is_handled(comment['id']):
                    continue
                if answered(comment, children, channel):
                    if not dry_run:
                        store.mark_handled(comment['id'], video, 'skipped', reason='pre-existing reply')
                        store.dequeue(comment['id'])
                    continue
                # Dry runs may queue work, but never mark it delivered or skipped.
                store.enqueue(dict(comment_id=comment['id'], video_id=video,
                    parent_id=top['id'], thread_id=thread['id'], author=comment['snippet'].get('authorDisplayName', ''),
                    text=comment['snippet'].get('textOriginal', ''),
                    context='' if comment['id'] == top['id'] else top['snippet'].get('textOriginal', '')))
    stats['videos'] = len(videos)
    titles = {}
    budget = int(os.getenv('COMMENT_MAX_PER_RUN', '40'))
    # Zero means no policy cutoff. YouTube quota/rate failures stay retryable.
    for entry in store.pending():
        if budget > 0 and stats['replied'] >= budget:
            break
        try:
            thread_response = service.commentThreads().list(
                part='snippet,replies', id=entry['thread_id'], textFormat='plainText').execute()
            threads = thread_response.get('items', [])
            if not threads:
                continue
            thread = threads[0]
            if (thread['snippet'].get('channelId') != channel or
                    thread['snippet'].get('videoId') != entry['video_id']):
                raise RuntimeError('Queued comment channel/video changed')
            children = replies(service, thread)
            candidates = [thread['snippet']['topLevelComment'], *children]
            comment = next((c for c in candidates if c['id'] == entry['comment_id']), None)
            if comment is None:
                if not dry_run:
                    store.mark_handled(entry['comment_id'], entry['video_id'], 'skipped', reason='deleted comment')
                    store.dequeue(entry['comment_id'])
                continue
            if author_id(comment) == channel or answered(comment, children, channel):
                if not dry_run:
                    store.mark_handled(entry['comment_id'], entry['video_id'], 'skipped', reason='pre-existing reply')
                    store.dequeue(entry['comment_id'])
                continue
            if entry['video_id'] not in titles:
                result = service.videos().list(part='snippet', id=entry['video_id']).execute()
                rows = result.get('items', [])
                if not rows or rows[0]['snippet']['channelId'] != channel:
                    raise RuntimeError('Queued video is not on expected channel')
                titles[entry['video_id']] = rows[0]['snippet']['title']
            stats['scanned'] += 1
            text = comment['snippet'].get('textOriginal', '')
            if entry['context']:
                text = f"Comentario inicial (contexto): {entry['context']}\nResposta do publico: {text}"
            decision = generate_reply(titles[entry['video_id']], text, entry['author'])
            if not decision['should_reply']:
                if decision['reason'].lower().startswith(('minimax error:', 'anthropic error:', 'gemini error:', 'no llm available')):
                    stats['errors'] += 1
                    break
                stats['skipped'] += 1
                if not dry_run:
                    store.mark_handled(entry['comment_id'], entry['video_id'], 'skipped', reason=decision['reason'])
                    store.dequeue(entry['comment_id'])
                continue
            reply = decision['reply']
            if entry['comment_id'] != entry['parent_id']:
                reply = entry['author'] + ' ' + reply
            if dry_run:
                stats['replied'] += 1
                log.info('[DRY] %s: %s', entry['comment_id'], reply)
                continue
            created = service.comments().insert(part='snippet', body={'snippet': {
                'parentId': entry['parent_id'], 'textOriginal': reply}}).execute()
            if not created.get('id'):
                raise RuntimeError('YouTube returned no reply receipt')
            store.mark_handled(entry['comment_id'], entry['video_id'], 'replied',
                reply_id=created['id'], reason='minimax: ' + decision['reason'])
            store.dequeue(entry['comment_id'])
            stats['replied'] += 1
            log.info('REPLY_RECEIPT comment=%s reply=%s video=%s', entry['comment_id'], created['id'], entry['video_id'])
            time.sleep(max(0, float(os.getenv('COMMENT_REPLY_DELAY_SECONDS', '5'))))
        except HttpError as exc:
            stats['errors'] += 1
            log.warning('YouTube comment operation failed: HTTP %s; queue retained', exc.resp.status)
            if exc.resp.status in (403, 429) or exc.resp.status >= 500:
                break
        except Exception:
            # Stop after ambiguous delivery; a fresh remote check reconciles next run.
            stats['errors'] += 1
            log.exception('Comment operation failed; queue retained')
            break
    stats['queued'] = len(store.pending())
    log.info('Full-channel responder: %s', stats)
    return stats
