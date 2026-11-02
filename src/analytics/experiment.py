"""Keep a random share of Shorts on the previous script so its effect is measured.

The evidence for shorter scripts is strong but observational. A small control group
for a few weeks turns it into a measurement, and lets the change undo itself if it
turns out to hurt. After the end date every Short gets the new script.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..config import settings

SHORT_SCRIPT = "short_script"
ARM_SHORT = "short"
ARM_CONTROL = "control"
HOLDOUT_SHARE = 0.2
HOLDOUT_UNTIL = date(2026, 11, 29)


def script_arm(store, *, now: datetime | None = None) -> str:
    """Which script a Short in this slot gets; retries in the same slot get the same one."""
    if store.growth_factor_disabled(SHORT_SCRIPT):
        return ARM_CONTROL
    local = (now or datetime.now(ZoneInfo(settings.timezone))).astimezone(ZoneInfo(settings.timezone))
    configured = os.getenv("SHORT_SCRIPT_HOLDOUT_SHARE")
    if configured is None and local.date() > HOLDOUT_UNTIL:
        return ARM_SHORT
    try:
        share = float(configured) if configured is not None else HOLDOUT_SHARE
    except ValueError:
        share = HOLDOUT_SHARE
    digest = hashlib.sha256(f"{SHORT_SCRIPT}:{local:%Y-%m-%d:%H}".encode()).hexdigest()
    return ARM_CONTROL if int(digest[:8], 16) / 0xFFFFFFFF < share else ARM_SHORT
