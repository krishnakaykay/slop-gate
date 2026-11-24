"""In-memory SSE event bus with sequence IDs, replay on Last-Event-ID, and 15s heartbeats."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class RunEventStream:
    events: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    done: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def publish(self, event_name: str, payload: dict[str, Any], *, terminal: bool = False) -> None:
        async with self.condition:
            seq = len(self.events) + 1
            self.events.append((seq, event_name, payload))
            if terminal:
                self.done = True
            self.condition.notify_all()


class SSEBus:
    def __init__(self) -> None:
        self._streams: dict[str, RunEventStream] = {}

    def get_or_create(self, run_id: str) -> RunEventStream:
        if run_id not in self._streams:
            self._streams[run_id] = RunEventStream()
        return self._streams[run_id]

    async def publish(self, run_id: str, event_name: str, payload: dict[str, Any], *, terminal: bool = False) -> None:
        stream = self.get_or_create(run_id)
        await stream.publish(event_name, payload, terminal=terminal)

    async def subscribe(self, run_id: str, last_event_id: int = 0) -> AsyncIterator[str]:
        stream = self.get_or_create(run_id)
        cursor = max(0, last_event_id)
        while True:
            async with stream.condition:
                while cursor >= len(stream.events) and not stream.done:
                    try:
                        await asyncio.wait_for(stream.condition.wait(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # Emit SSE comment heartbeat to keep proxies/browsers alive
                        yield ": heartbeat\n\n"
                batch = stream.events[cursor:]
                is_done = stream.done

            for seq, ev_name, data in batch:
                cursor = seq
                yield f"id: {seq}\nevent: {ev_name}\ndata: {json.dumps(data)}\n\n"

            if is_done and cursor >= len(stream.events):
                break


sse_bus = SSEBus()
