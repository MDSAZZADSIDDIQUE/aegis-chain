"""Shared asyncio pub-sub broadcaster for SSE push events.

Usage
-----
Broadcasting (from any async context):

    from app.core.events import broadcast
    await broadcast("pipeline_complete", {"proposals": 3})

Subscribing (inside an SSE generator):

    from app.core.events import subscribe, unsubscribe
    q = await subscribe()
    try:
        msg = await asyncio.wait_for(q.get(), timeout=15.0)
    finally:
        unsubscribe(q)

Event envelope written to each subscriber queue:
    {"type": "<event_type>", "data": {<payload>}}
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger("aegis.events")

# Set of active subscriber queues (one per connected SSE client)
_subscribers: set[asyncio.Queue] = set()

# Maximum events buffered per client before we start dropping for slow readers
_QUEUE_MAX = 64

# ── WebSocket pipeline-progress clients ──────────────────────────────────────
# One entry per open /ws/pipeline connection.  Each is a raw FastAPI WebSocket
# so we can await ws.send_json() directly without a separate queue layer.

_ws_clients: set["WebSocket"] = set()


def ws_connect(ws: "WebSocket") -> None:
    """Register a new /ws/pipeline WebSocket client."""
    _ws_clients.add(ws)
    logger.debug("WS pipeline client connected (total=%d)", len(_ws_clients))


def ws_disconnect(ws: "WebSocket") -> None:
    """Remove a /ws/pipeline WebSocket client."""
    _ws_clients.discard(ws)
    logger.debug("WS pipeline client disconnected (total=%d)", len(_ws_clients))


def ws_client_count() -> int:
    """Return the number of active /ws/pipeline connections."""
    return len(_ws_clients)


async def ws_broadcast(payload: dict[str, Any]) -> None:
    """Push a progress event to every connected /ws/pipeline client.

    Silently removes dead connections; never raises.
    """
    if not _ws_clients:
        return
    dead: set["WebSocket"] = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


async def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber.  Returns the dedicated queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    logger.debug("SSE subscriber added  (total=%d)", len(_subscribers))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a subscriber queue (called when SSE connection closes)."""
    _subscribers.discard(q)
    logger.debug("SSE subscriber removed (total=%d)", len(_subscribers))


def subscriber_count() -> int:
    """Return the number of currently connected SSE clients."""
    return len(_subscribers)


async def broadcast(event_type: str, payload: dict[str, Any]) -> int:
    """Push an event to every connected SSE client.

    Slow clients whose queue is full are silently dropped so they cannot
    back-pressure the rest of the system.

    Returns:
        Number of subscribers that actually received the event.
    """
    if not _subscribers:
        return 0

    envelope = {"type": event_type, "data": payload}
    dead: set[asyncio.Queue] = set()
    sent = 0

    for q in _subscribers:
        try:
            q.put_nowait(envelope)
            sent += 1
        except asyncio.QueueFull:
            logger.debug(
                "SSE queue full for one client — dropping '%s' event", event_type
            )
            dead.add(q)

    _subscribers.difference_update(dead)
    logger.debug("Broadcast '%s' → %d/%d subscribers", event_type, sent, len(_subscribers) + len(dead))
    return sent
