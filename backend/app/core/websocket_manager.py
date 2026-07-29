"""
WebSocket connection manager.
Handles live order state, fill notifications and price streaming.
FR-A-15: order status without page refresh.
FR-L-03: prices to subscribed clients within 1 second.
"""
import json
import asyncio
from typing import Dict, Set
from fastapi import WebSocket
import structlog

log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        # user_id -> set of WebSocket connections
        self._user_connections: Dict[str, Set[WebSocket]] = {}
        # Subscribed instrument_ids -> set of WebSocket connections
        self._price_subscriptions: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(websocket)
        log.info("WebSocket connected", user_id=user_id)

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        # Remove from price subscriptions
        for subs in self._price_subscriptions.values():
            subs.discard(websocket)
        log.info("WebSocket disconnected", user_id=user_id)

    def subscribe_prices(self, websocket: WebSocket, instrument_id: str):
        if instrument_id not in self._price_subscriptions:
            self._price_subscriptions[instrument_id] = set()
        self._price_subscriptions[instrument_id].add(websocket)

    async def send_to_user(self, user_id: str, message: dict):
        """Push a message to all connections for a user (order updates, alerts)."""
        conns = self._user_connections.get(user_id, set()).copy()
        dead = set()
        for ws in conns:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._user_connections.get(user_id, set()).discard(ws)

    async def broadcast_price(self, instrument_id: str, price_data: dict):
        """Broadcast a price tick to all subscribers of that instrument."""
        subs = self._price_subscriptions.get(instrument_id, set()).copy()
        dead = set()
        for ws in subs:
            try:
                await ws.send_text(json.dumps({"type": "price", "data": price_data}))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._price_subscriptions.get(instrument_id, set()).discard(ws)

    async def broadcast_all(self, message: dict):
        """Broadcast to every connected user (e.g. kill switch activation)."""
        msg = json.dumps(message)
        for conns in self._user_connections.values():
            for ws in conns.copy():
                try:
                    await ws.send_text(msg)
                except Exception:
                    pass


# Singleton — imported by endpoints and services
manager = ConnectionManager()
