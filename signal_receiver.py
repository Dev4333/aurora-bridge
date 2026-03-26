"""Signal Receiver — SSE client + REST polling fallback.

Maintains an SSE connection to /bridge/signals/stream for real-time signal delivery.
Falls back to polling /bridge/signals/pending every N seconds if SSE disconnects.
Deduplicates signals using a local set of seen IDs.
"""

import asyncio
import json
import logging
from typing import AsyncIterator

import aiohttp

from models import Signal

logger = logging.getLogger("aurora-bridge")


class SignalReceiver:
    """Receives signals from Aurora API via SSE + polling fallback."""

    def __init__(self, token: str, api_url: str, poll_interval: int = 5):
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.poll_interval = poll_interval
        self.seen_ids: set[str] = set()
        self._signal_queue: asyncio.Queue[Signal] = asyncio.Queue()
        self._running = False

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def fetch_pending(self) -> list[Signal]:
        """Fetch all pending signals (used on startup + polling fallback)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_url}/bridge/signals/pending",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 401:
                        logger.error("Authentication failed — token may be expired or revoked")
                        return []
                    if resp.status != 200:
                        logger.warning(f"Failed to fetch pending signals: HTTP {resp.status}")
                        return []
                    data = await resp.json()
                    signals = [Signal(**s) for s in data.get("signals", [])]
                    return [s for s in signals if s.id not in self.seen_ids]
        except Exception as e:
            logger.error(f"Error fetching pending signals: {e}")
            return []

    async def ack(self, signal_id: str, status: str, mt5_ticket: str | None = None,
                  failure_reason: str | None = None):
        """Report signal status back to Aurora API."""
        try:
            body = {"status": status}
            if mt5_ticket:
                body["mt5Ticket"] = mt5_ticket
            if failure_reason:
                body["failureReason"] = failure_reason

            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    f"{self.api_url}/bridge/signals/{signal_id}/status",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Signal {signal_id[:8]} status → {status}")
                    else:
                        logger.warning(f"Failed to ack signal {signal_id[:8]}: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Error acking signal {signal_id[:8]}: {e}")

    async def _sse_loop(self):
        """Connect to SSE stream and yield signals."""
        logger.info("Connecting to SSE stream...")
        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self.api_url}/bridge/signals/stream",
                    headers=self.headers,
                ) as resp:
                    if resp.status == 401:
                        logger.error("SSE auth failed — token may be expired")
                        return
                    if resp.status != 200:
                        logger.warning(f"SSE connection failed: HTTP {resp.status}")
                        return

                    logger.info("SSE stream connected ✓")
                    buffer = ""
                    async for chunk in resp.content:
                        if not self._running:
                            break
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n\n" in buffer:
                            message, buffer = buffer.split("\n\n", 1)
                            await self._parse_sse_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"SSE connection lost: {e}")

    async def _parse_sse_message(self, raw: str):
        """Parse an SSE message and queue the signal."""
        event_type = ""
        data = ""
        for line in raw.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = line[6:]

        if event_type == "signal" and data:
            try:
                signal = Signal(**json.loads(data))
                if signal.id not in self.seen_ids:
                    self.seen_ids.add(signal.id)
                    await self._signal_queue.put(signal)
                    logger.info(f"SSE → {signal.pair} {signal.direction} ({signal.id[:8]})")
            except Exception as e:
                logger.warning(f"Failed to parse SSE signal: {e}")
        elif event_type == "connected":
            logger.info("SSE handshake complete")
        elif event_type == "ping":
            pass  # keepalive

    async def _poll_loop(self):
        """Polling fallback: fetch pending signals periodically."""
        while self._running:
            try:
                signals = await self.fetch_pending()
                for signal in signals:
                    if signal.id not in self.seen_ids:
                        self.seen_ids.add(signal.id)
                        await self._signal_queue.put(signal)
                        logger.info(f"POLL → {signal.pair} {signal.direction} ({signal.id[:8]})")
            except Exception as e:
                logger.warning(f"Poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def stream(self) -> AsyncIterator[Signal]:
        """Main stream: runs SSE with polling fallback. Yields signals."""
        self._running = True

        # Start polling fallback in background
        poll_task = asyncio.create_task(self._poll_loop())

        # SSE with auto-reconnect
        sse_task = None
        try:
            while self._running:
                sse_task = asyncio.create_task(self._sse_loop())

                # Yield signals from the queue while SSE is running
                while self._running:
                    try:
                        signal = await asyncio.wait_for(self._signal_queue.get(), timeout=1.0)
                        yield signal
                    except asyncio.TimeoutError:
                        # Check if SSE task died
                        if sse_task.done():
                            logger.info("SSE disconnected, reconnecting in 5s...")
                            await asyncio.sleep(5)
                            break  # Reconnect
                        continue
        finally:
            self._running = False
            poll_task.cancel()
            if sse_task and not sse_task.done():
                sse_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

    def stop(self):
        """Stop the receiver."""
        self._running = False
