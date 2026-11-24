"""Thread-safe pub/sub bridge between sync services and async WebSocket clients."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("cloudguard.realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self.channels: dict[str, set[WebSocket]] = {"monitoring": set(), "alerts": set()}
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def connect(self, channel: str, ws: WebSocket) -> None:
        await ws.accept()
        self.channels.setdefault(channel, set()).add(ws)

    def disconnect(self, channel: str, ws: WebSocket) -> None:
        self.channels.get(channel, set()).discard(ws)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        data = json.dumps(message, default=str)
        dead = []
        for ws in list(self.channels.get(channel, ())):
            try:
                await ws.send_text(data)
            except Exception:  # client went away
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Callable from any thread."""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(channel, message), self.loop)
        except RuntimeError:
            log.debug("event loop unavailable for publish")


manager = ConnectionManager()
