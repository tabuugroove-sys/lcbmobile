"""Compare the short script with its control group, and stop it if it clearly hurts."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from uuid import uuid4

from .experiment import ARM_CONTROL, ARM_SHORT, HOLDOUT_UNTIL, SHORT_SCRIPT

log = logging.getLogger(__name__)

MATURE_DAYS = 7
MIN_ARM_SIZE = 10
# Both must hold: one lucky hit in the control group alone cannot switch the change off.
HARM_CAPPED_MEAN_RATIO = 0.6
HARM_MEDIAN_RATIO = 0.7


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def build_scorecard(rows: list[dict], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    mature = []
    for row in rows:
        assigned = datetime.fromisoformat(str(row["assigned_at"])).replace(tzinfo=timezone.utc)
        # Later Shorts have no control group beside them; channel drift would read as an effect.
        if now - assigned < timedelta(days=MATURE_DAYS) or assigned.date() > HOLDOUT_UNTIL:
            continue
        views = row.get("views_7d")
        mature.append({**row, "outcome": int(row["views"] if views is None else views)})
    cap = _percentile([r["outcome"] for r in mature], 0.95) if mature else 0
    arms = {}
    for arm in (ARM_SHORT, ARM_CONTROL):
        members = [r for r in mature if r["script_arm"] == arm]
        values = [r["outcome"] for r in members]
        retention = [r["context"]["avg_view_pct"] for r in members if "avg_view_pct" in r["context"]]
        arms[arm] = {
            "n": len(members),
            "mean_views": round(mean(values), 1) if values else None,
            "median_views": median(values) if values else None,
            "capped_mean_views": round(mean(min(v, cap) for v in values), 1) if values else None,
            "mean_avg_view_pct": round(mean(retention), 1) if retention else None,
            "mean_script_words": round(mean(r["script_words"] for r in members), 1) if members else None,
        }
    return {"generated_at": now.isoformat(), "assigned": len(rows), "mature": len(mature),
            "outcome": f"public views about {MATURE_DAYS} days after publication", "arms": arms,
            "harm": is_harmful(arms)}


def is_harmful(arms: dict) -> bool:
    short, control = arms[ARM_SHORT], arms[ARM_CONTROL]
    if short["n"] < MIN_ARM_SIZE or control["n"] < MIN_ARM_SIZE:
        return False
    if not control["capped_mean_views"] or not control["median_views"]:
        return False
    return (short["capped_mean_views"] / control["capped_mean_views"] < HARM_CAPPED_MEAN_RATIO
            and short["median_views"] / control["median_views"] < HARM_MEDIAN_RATIO)


def update_scorecard(store, output_dir: Path, *, now: datetime | None = None) -> dict:
    card = build_scorecard(store.growth_assignment_rows(), now=now)
    folder = output_dir / "analytics"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "growth-scorecard.json"
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(card, indent=2), encoding="utf-8")
    temporary.replace(path)
    if card["harm"] and not store.growth_factor_disabled(SHORT_SCRIPT):
        store.disable_growth_factor(SHORT_SCRIPT)
        log.error("Short script looks harmful; returning every Short to the previous script: %s", card["arms"])
        from ..notify import notify_urgent
        notify_urgent(
            "LCBMobile: the short Shorts script did clearly worse than its control group, "
            f"so the previous script is back for every Short. {json.dumps(card['arms'])}",
            kind="growth_guard",
        )
    return card
