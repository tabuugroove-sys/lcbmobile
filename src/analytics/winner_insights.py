"""Small, auditable audience signals, never causal claims about a video."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from uuid import uuid4

MAX_TOPIC_BONUS = 0.6
MIN_EXAMPLES = 3


def _age_days(row: dict, now: datetime) -> float | None:
    try:
        stamp = datetime.fromisoformat(row['context']['published_at'].replace('Z', '+00:00'))
        stamp = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc)
        return (now - stamp.astimezone(timezone.utc)).total_seconds() / 86400
    except (KeyError, TypeError, ValueError):
        return None


def _bucket(days: float) -> str:
    return '3-14d' if days < 14 else '14-60d' if days < 60 else '60-180d' if days < 180 else '180d+'


def _visual_evidence(row: dict, output_dir: Path | None) -> dict:
    if output_dir is None:
        return {'status': 'unknown'}
    key = str(row.get('fingerprint', '')).replace('/', '_').replace(':', '_')[-80:]
    if not key or key in {'.', '..'} or '\\' in key:
        return {'status': 'unknown'}
    path = output_dir / key / 'render_manifest.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        duration = data.get('duration_seconds') or 0
        scenes = data.get('scene_count') or 0
        return {'status': 'render_manifest', 'style': data.get('style'),
                'scene_count': data.get('scene_count'),
                'photo_count': data.get('licensed_photo_count'),
                'video_count': data.get('licensed_video_count'),
                'mean_scene_seconds': round(duration / scenes, 2) if scenes else None}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'status': 'unknown'}


def build_insights(examples: list[dict], *, now: datetime | None = None,
                   output_dir: Path | None = None) -> dict:
    from .scorer import _topic_labels

    now = now or datetime.now(timezone.utc)
    # Old DBs can contain repeated publication joins; one upload is one example.
    unique = {str(r['video_id']): r for r in examples if r.get('video_id')}
    rows = [r for r in unique.values() if r.get('content_format') == 'short']
    mature, cohorts = [], defaultdict(list)
    for row in rows:
        age = _age_days(row, now)
        try:
            collected = datetime.fromisoformat(str(row['analytics_collected_at']).replace('Z', '+00:00'))
            stale_days = (now - collected.replace(tzinfo=collected.tzinfo or timezone.utc)).total_seconds() / 86400
        except (ValueError, KeyError, TypeError):
            continue
        if age is None or age < 3 or not 0 <= stale_days <= 7:
            continue
        cohort = _bucket(age)
        mature.append((row, cohort))
        cohorts[cohort].append(row)

    residuals, eligible = {}, []
    for row, cohort in mature:
        peers = cohorts[cohort]
        if len(peers) < 6:
            continue
        # Age cohorts reduce lifetime exposure bias, but are not matched experiments.
        views = math.log1p(max(0, int(row.get('view_count') or 0)))
        subs = math.log1p(max(0, int(row.get('subscribers_gained') or 0)))
        base_views = median(math.log1p(max(0, int(p.get('view_count') or 0))) for p in peers)
        base_subs = median(math.log1p(max(0, int(p.get('subscribers_gained') or 0))) for p in peers)
        residuals[row['video_id']] = max(-2, min(2, .75*(views-base_views) + .25*(subs-base_subs)))
        eligible.append(row)

    grouped = defaultdict(list)
    for row in eligible:
        for topic in _topic_labels(str(row.get('title') or '')):
            grouped[topic].append(row)
    topics = {}
    for topic, members in grouped.items():
        ids = {r['video_id'] for r in members}
        controls = [r for r in eligible if r['video_id'] not in ids]
        enough = len(members) >= MIN_EXAMPLES and len(controls) >= MIN_EXAMPLES
        lift = mean(residuals[r['video_id']] for r in members) - mean(
            residuals[r['video_id']] for r in controls) if enough else 0
        bonus = max(-MAX_TOPIC_BONUS, min(MAX_TOPIC_BONUS, lift * len(members)/(len(members)+10)))
        topics[topic] = {
            'sample_size': len(members), 'control_size': len(controls),
            'median_views': median(int(r.get('view_count') or 0) for r in members),
            'subscribers_gained': sum(int(r.get('subscribers_gained') or 0) for r in members),
            'bonus': round(bonus, 4), 'evidence': 'association_not_causation',
            'confidence': 'sparse' if not enough else 'limited' if len(members) < 10 else 'observational',
            'example_ids': [r['video_id'] for r in sorted(members, key=lambda r: int(r.get('view_count') or 0), reverse=True)[:5]],
        }

    top = []
    for row in sorted(rows, key=lambda r: int(r.get('view_count') or 0), reverse=True)[:25]:
        views, subs = int(row.get('view_count') or 0), int(row.get('subscribers_gained') or 0)
        top.append({
            'video_id': row['video_id'], 'title': row['title'], 'views': views,
            'subscribers_gained': subs, 'subscribers_per_1000_views': round(1000*subs/views, 2) if views else None,
            'topics': sorted(_topic_labels(row['title'])), 'context': row.get('context', {}),
            'visual_evidence': _visual_evidence(row, output_dir),
        })
    visuals = defaultdict(list)
    for row in eligible:
        evidence = _visual_evidence(row, output_dir)
        if evidence['status'] == 'render_manifest' and evidence.get('video_count') is not None:
            visuals['with_video' if evidence['video_count'] else 'photos_only'].append(row)
    visual_groups = {k: {'n': len(v), 'median_views': median(int(r['view_count']) for r in v),
                         'mean_age_adjusted_outcome': round(mean(residuals[r['video_id']] for r in v), 3)}
                     for k, v in visuals.items()}
    durations = defaultdict(list)
    for row in eligible:
        seconds = row.get('context', {}).get('duration_seconds') or 0
        if seconds:
            durations['<=35s' if seconds <= 35 else '36-45s' if seconds <= 45 else '>45s'].append(row)
    duration_groups = {
        k: {'n': len(v), 'median_views': median(int(r['view_count']) for r in v),
            'mean_age_adjusted_outcome': round(mean(residuals[r['video_id']] for r in v), 3)}
        for k, v in durations.items()
    }
    return {
        'version': 1, 'generated_at': now.isoformat(), 'sort': 'lifetime_views_desc',
        'shorts_count': len(rows), 'training_count': len(eligible),
        'max_topic_bonus': MAX_TOPIC_BONUS, 'topics': topics, 'top_videos': top,
        'visual_groups': visual_groups, 'duration_groups': duration_groups,
        'visual_coverage': sum(len(v) for v in visuals.values()),
        'limitations': [
            'Topics are title-derived labels, not an explanation of causality.',
            'Lifetime views are compared within broad upload-age cohorts; exposure still differs.',
            'Missing render manifests mean unknown editing, not a static photo.',
            'Thumbnail appeal and first-frame quality require visual review; title/API data cannot prove them.',
            'Visual groups are descriptive only and never change news selection or montage automatically.',
        ],
    }


def topic_bonus(profile: dict, labels: set[str]) -> float:
    values = [profile['topics'][label]['bonus'] for label in labels if label in profile.get('topics', {})]
    return max(-MAX_TOPIC_BONUS, min(MAX_TOPIC_BONUS, mean(values))) if values else 0.0


def write_insights(store, output_dir: Path) -> Path:
    profile = build_insights(store.analytics_examples(None), output_dir=output_dir)
    folder = output_dir / 'analytics'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'winner-insights.json'
    temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
    temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    return path
