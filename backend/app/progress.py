"""
Stage 2.2 — In-process Pub/Sub Progress Bus for Server-Sent Events (SSE).
Decoupled from HTTP so async job workers and executor callbacks can publish
structured progress and theme-readiness events to connected clients.
"""

import asyncio
from collections import defaultdict
from typing import AsyncIterator, Dict, Any, Optional


class ProgressBus:
    """In-process pub/sub for job progress. One bounded queue per subscriber."""

    def __init__(self):
        self._subs: Dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._last: Dict[str, dict] = {}  # replay for late/reconnecting subscribers

    def publish(self, job_id: str, event: Dict[str, Any]) -> None:
        prev = self._last.get(job_id)
        if prev and prev.get("status") in ("completed", "failed") and event.get("status") not in ("completed", "failed"):
            return
        self._last[job_id] = event
        for q in list(self._subs.get(job_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop; next state event supersedes
                pass

    def publish_threadsafe(
        self,
        loop: Optional[asyncio.AbstractEventLoop],
        job_id: str,
        event: Dict[str, Any],
    ) -> None:
        """Marshal a publish call from a worker pool thread onto the event loop."""
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.publish, job_id, event)
        else:
            self.publish(job_id, event)

    async def subscribe(self, job_id: str) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subs[job_id].append(q)
        try:
            if job_id in self._last:
                initial = self._last[job_id]
                yield initial
                if initial.get("status") in ("completed", "failed"):
                    return
            while True:
                event = await q.get()
                yield event
                if event.get("status") in ("completed", "failed"):
                    return
        finally:
            if job_id in self._subs and q in self._subs[job_id]:
                self._subs[job_id].remove(q)
            if not self._subs.get(job_id):
                self._subs.pop(job_id, None)
                self._last.pop(job_id, None)


progress_bus = ProgressBus()
