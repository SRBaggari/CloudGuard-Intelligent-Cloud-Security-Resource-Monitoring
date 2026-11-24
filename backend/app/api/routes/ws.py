"""WebSocket endpoints. Authenticate with ?token=<access token>."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.core.deps import user_from_token
from app.realtime.bus import manager

router = APIRouter()


async def _serve(ws: WebSocket, channel: str) -> None:
    token = ws.query_params.get("token", "")
    with SessionLocal() as db:
        try:
            user = user_from_token(db, token)
        except HTTPException:
            await ws.close(code=4401, reason="Unauthorized")
            return
    await manager.connect(channel, ws)
    await ws.send_json({"type": "hello", "channel": channel, "user": user.username})
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(channel, ws)


@router.websocket("/ws/monitoring")
async def ws_monitoring(ws: WebSocket):
    await _serve(ws, "monitoring")


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await _serve(ws, "alerts")
