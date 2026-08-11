"""One router per thing the interface does."""

from __future__ import annotations

from . import bounties, meta, scan, triage

__all__ = ["bounties", "meta", "scan", "triage"]
