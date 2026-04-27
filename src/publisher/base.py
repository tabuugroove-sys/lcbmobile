"""Common publisher interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import GeneratedAssets, RewrittenPost


@dataclass
class PublishResult:
    platform: str
    ok: bool
    remote_id: str | None = None
    error: str | None = None
    url: str | None = None


class Publisher(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult: ...
