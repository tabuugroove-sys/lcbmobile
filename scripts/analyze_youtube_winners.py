"""Read-only channel audit. Never uploads, comments, or changes published videos."""
from __future__ import annotations

import argparse
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urlparse

from src.analytics.winner_insights import _age_days, _bucket, write_insights
from src.config import settings
from src.storage import Store


def review_pairs(rows: list[dict], count: int = 10) -> list[tuple[dict, dict | None]]:
    now = datetime.now(timezone.utc)
    rows = [r for r in rows if r.get('content_format') == 'short' and (_age_days(r, now) or 0) >= 3]
    ordered = sorted(rows, key=lambda r: r['view_count'], reverse=True)
    used, pairs = set(), []
    for winner in ordered[:count]:
        age = _age_days(winner, now)
        cohort = [r for r in rows if _bucket(_age_days(r, now)) == _bucket(age)]
        baseline = median(r['view_count'] for r in cohort)
        controls = [r for r in cohort if r['video_id'] not in used and r['view_count'] <= baseline
                    and r['video_id'] != winner['video_id']]
        control = min(controls, key=lambda r: abs(_age_days(r, now)-age)) if controls else None
        if control:
            used.add(control['video_id'])
        pairs.append((winner, control))
    return pairs


def visual_review(rows: list[dict], folder: Path) -> Path:
    import cv2
    import httpx
    import numpy as np
    from PIL import Image, ImageDraw

    folder.mkdir(parents=True, exist_ok=True)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    pairs = review_pairs(rows)
    sheet = Image.new('RGB', (1000, max(1, len(pairs))*330), '#ededed')
    draw, evidence = ImageDraw.Draw(sheet), []
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        for index, pair in enumerate(pairs):
            pair_data = []
            for column, row in enumerate(pair):
                if not row:
                    pair_data.append(None)
                    continue
                video_id = row['video_id']
                x, y = column*500, index*330
                record = {'video_id': video_id, 'views': row['view_count'], 'title': row['title'],
                          'subscribers_gained': row['subscribers_gained'], 'status': 'unknown'}
                try:
                    url = row.get('context', {}).get('thumbnail_url') or ''
                    parsed = urlparse(url)
                    if parsed.scheme != 'https' or parsed.hostname not in {'i.ytimg.com', 'img.youtube.com'}:
                        raise ValueError('Not an official YouTube thumbnail URL')
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', video_id):
                        raise ValueError('Invalid video ID')
                    path = folder / f'{video_id}.jpg'
                    if path.exists():
                        payload = path.read_bytes()
                    else:
                        chunks, size = [], 0
                        with client.stream('GET', url) as response:
                            response.raise_for_status()
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > 3_000_000:
                                    raise ValueError('Thumbnail too large')
                                chunks.append(chunk)
                        payload = b''.join(chunks)
                    with Image.open(io.BytesIO(payload)) as raw:
                        pic = raw.convert('RGB')
                    pic.save(path)
                    gray = cv2.cvtColor(np.array(pic), cv2.COLOR_RGB2GRAY)
                    faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(18, 18))
                    area = pic.width * pic.height
                    record.update(status='measured_thumbnail', face_count_estimate=len(faces),
                                  largest_face_fraction=round(max((w*h/area for _, _, w, h in faces), default=0), 4),
                                  dark_pixel_fraction=round(float(np.mean(gray < 25)), 3))
                    pic.thumbnail((480, 270))
                    sheet.paste(pic, (x+(480-pic.width)//2, y))
                except (OSError, ValueError, httpx.HTTPError, cv2.error) as exc:
                    record['error'] = str(exc)[:200]
                label = 'TOP' if column == 0 else 'AGE-MATCHED COMPARISON'
                draw.text((x+10, y+275), f'{label}: {video_id}', fill='black')
                draw.text((x+10, y+293), f"Views: {row['view_count']}  Subscribers: {row['subscribers_gained']}", fill='black')
                pair_data.append(record)
            evidence.append(pair_data)
    sheet.save(folder / 'review.jpg')
    result = {
        'pairs': evidence,
        'selection': 'Top lifetime views vs below-median videos in the same upload-age cohort.',
        'limitations': ['Face detector estimates can be wrong, especially on small faces.',
                        'A thumbnail is not evidence of the full montage or its opening frame.',
                        'Topic, exposure, timing and audience are not controlled; no causal conclusion.',
                        'Visual measurements do not affect news ranking.'],
    }
    path = folder / 'review.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def write_report(profile: dict, folder: Path) -> Path:
    lines = ['# YouTube Audience Audit', '', f"Generated: {profile['generated_at']}",
             f"All-time Shorts: {profile['shorts_count']}; mature, fresh examples: {profile['training_count']}.",
             'Outcomes: views and subscribers gained. Likes/comments are not objectives.', '',
             '## All-Time Leaders', '', '| Video | Views | Subscribers | Subs / 1,000 views |',
             '| --- | ---: | ---: | ---: |']
    for row in profile['top_videos']:
        title = row['title'].replace('|', '/').replace('\n', ' ')
        lines.append(f"| [{title}](https://www.youtube.com/watch?v={row['video_id']}) | {row['views']} | "
                     f"{row['subscribers_gained']} | {row['subscribers_per_1000_views']} |")
    lines += ['', '## Topic Associations', '', '| Topic | Examples | Controls | Median views | Ranking adjustment |',
              '| --- | ---: | ---: | ---: | ---: |']
    for topic, data in sorted(profile['topics'].items(), key=lambda p: p[1]['bonus'], reverse=True):
        lines.append(f"| {topic} | {data['sample_size']} | {data['control_size']} | {data['median_views']} | "
                     f"{.8*data['bonus']:+.3f} |")
    lines += ['', 'New topic adjustment is capped at +/-0.48 points. Existing editorial, freshness,',
              'deduplication and media eligibility rules still apply. Shorts signals do not transfer to long-form.',
              '', '## Visual Evidence', '',
              f"Render manifests available for {profile['visual_coverage']} training examples.",
              'Montage counts and duration groups are descriptive, not proof of an effective style.',
              'Optional visual-review/review.jpg compares winners with age-matched lower-view examples.',
              'Test one change at a time (opening image OR shot pacing), with balanced topics and comparable upload ages.',
              '', '```json', json.dumps({'montage': profile['visual_groups'], 'duration': profile['duration_groups']}, indent=2),
              '```', '', '## Limits', '']
    lines.extend('- '+line for line in profile['limitations'])
    path = folder / 'winner-report.md'
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return path


def refresh_trend(service, profile: dict, folder: Path) -> dict:
    # Leave two days for Analytics processing. Use the returned latest date,
    # not today's partial totals, to define equal seven-day windows.
    end = datetime.now(timezone.utc).date() - timedelta(days=2)
    start = end - timedelta(days=27)
    args = dict(ids='channel==MINE', startDate=start.isoformat(), endDate=end.isoformat(),
                metrics='views,subscribersGained', dimensions='day', sort='day', maxResults=100)
    channel = service.reports().query(**args).execute().get('rows', []) or []
    if not channel or not profile['top_videos']:
        return {}
    latest = datetime.fromisoformat(channel[-1][0]).date()
    boundary = (latest-timedelta(days=6)).isoformat()
    previous = (latest-timedelta(days=13)).isoformat()
    leader_id = profile['top_videos'][0]['video_id']
    leader = service.reports().query(**args, filters='video=='+leader_id).execute().get('rows', []) or []

    def totals(rows, begin, finish):
        return {name: sum(int(r[index]) for r in rows if begin <= r[0] <= finish)
                for index, name in [(1, 'views'), (2, 'subscribers_gained')]}

    prev_end = (latest-timedelta(days=7)).isoformat()
    result = {'latest_day': latest.isoformat(), 'recent_start': boundary, 'previous_start': previous,
              'previous_end': prev_end, 'leader_video_id': leader_id}
    for label, rows in [('channel', channel), ('leader', leader)]:
        result[label] = {'recent': totals(rows, boundary, latest.isoformat()),
                         'previous': totals(rows, previous, prev_end)}
    (folder / 'trend.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Read the full authenticated channel inventory and Analytics API')
    parser.add_argument('--visual-review', action='store_true', help='Download official thumbnails for a comparison sheet')
    args = parser.parse_args()
    store = Store(settings.db_path)
    if args.refresh:
        from src.analytics.youtube_metrics import _oauth_credentials, _analytics_service, _data_service, _refresh_channel_history
        credentials = _oauth_credentials()
        analytics = _analytics_service(credentials)
        if analytics is None:
            raise SystemExit('Analytics OAuth authorization is required; no report refresh performed')
        print(f'Refreshed {_refresh_channel_history(store, analytics, _data_service(credentials))} videos')
    path = write_insights(store, settings.output_dir)
    profile = json.loads(path.read_text(encoding='utf-8'))
    report = write_report(profile, path.parent)
    if args.refresh:
        try:
            trend = refresh_trend(analytics, profile, path.parent)
            if trend:
                with report.open('a', encoding='utf-8') as stream:
                    stream.write('\n## Recent Trend\n\nEqual seven-day windows; attribution is arithmetic, not a causal claim.\n\n```json\n')
                    stream.write(json.dumps(trend, indent=2)+'\n```\n')
        except Exception as exc:
            print(f'Trend unavailable; all-time report retained: {type(exc).__name__}')
    print(report)
    if args.visual_review:
        print(visual_review(store.analytics_examples(None), path.parent / 'visual-review'))


if __name__ == '__main__':
    main()
