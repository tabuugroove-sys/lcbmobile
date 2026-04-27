"""Loads source definitions from YAML."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    type: str
    url: str
    category: str
    weight: float = 1.0


def load_sources(path: Path) -> list[Source]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    raw = data.get("sources", [])
    return [Source(**entry) for entry in raw]
