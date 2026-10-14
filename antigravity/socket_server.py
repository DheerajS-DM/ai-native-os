"""socket_server.py — Unix domain socket server bridging sidebar to agent."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import context
from agent import AgentSession, process_message
from logger import get_logger, setup_global_exception_handler

setup_global_exception_handler("socket_server")
log = get_logger("socket_server")

SOCKET_PATH = "/tmp/nexus.sock"
_client_counter = 0

class ClientHandler:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        global _client_counter
        _client_counter += 1
        self.client_id = _client_counter
        self.reader = reader
        self.writer = writer
        self.session = AgentSession()
        self._confirm_event = asyncio.Event()
        self._confirm_result = False
        log.info("[Client #%d] Connection established", self.client_id)

    async def send(self, msg: dict) -> None:
        try:
            data = json.dumps(msg) + "\n"
            msg_type = msg.get("type", "unknown")
            log.debug("[Client #%d] Sending message type '%s': %.120s...", self.client_id, msg_type, json.dumps(msg))
            self.writer.write(data.encode())
            await self.writer.drain()
        except Exception as e:
            log.warning("[Client #%d] Failed to send message: %s", self.client_id, e)

    async def wait_confirm(self) -> bool:
        log.info("[Client #%d] Waiting for user confirmation response...", self.client_id)
        self._confirm_event.clear()
        await self._confirm_event.wait()
        log.info("[Client #%d] Received confirmation verdict: %s", self.client_id, self._confirm_result)
        return self._confirm_result

    async def handle(self) -> None:
        try:
            while True:
                try:
                    line = await self.reader.readline()
                    if not line:
                        log.info("[Client #%d] Client disconnected (EOF)", self.client_id)
                        break
                    decoded = line.decode().strip()
                    if not decoded:
                        continue
                    log.debug("[Client #%d] Raw packet received: %.120s", self.client_id, decoded)
                    msg = json.loads(decoded)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    log.warning("[Client #%d] Failed to decode incoming line: %s", self.client_id, e)
                    continue
                except Exception as e:
                    log.error("[Client #%d] Socket read error: %s", self.client_id, e, exc_info=True)
                    break

                msg_type = msg.get("type")
                log.info("[Client #%d] Processing incoming action: %s", self.client_id, msg_type)

                if msg_type == "chat":
                    text = msg.get("text", "")
                    log.info("[Client #%d] Chat request (text len: %d chars)", self.client_id, len(text))
                    await process_message(
                        text,
                        self.session,
                        send_fn=self.send,
                        confirm_fn=self.wait_confirm,
                    )
                elif msg_type == "chat_multimodal":
                    text = msg.get("text", "")
                    media = msg.get("media", [])
                    log.info("[Client #%d] Multimodal chat request (media items: %d)", self.client_id, len(media))
                    await process_message(
                        text,
                        self.session,
                        send_fn=self.send,
                        confirm_fn=self.wait_confirm,
                        media=media,
                    )
                elif msg_type == "confirm_response":
                    self._confirm_result = bool(msg.get("approved", False))
                    log.info("[Client #%d] Confirmation set to %s", self.client_id, self._confirm_result)
                    self._confirm_event.set()
                elif msg_type == "unlock":
                    if self.session.guard_state:
                        self.session.guard_state.reset()
                    log.info("[Client #%d] Safeguard state reset requested and executed", self.client_id)
                    await self.send({"type": "info", "text": "Safeguard lock reset."})
                elif msg_type == "clear_context":
                    context.clear_conversation()
                    log.info("[Client #%d] Conversation history cleared", self.client_id)
                    await self.send({"type": "info", "text": "Conversation history cleared."})
                else:
                    log.warning("[Client #%d] Unrecognized message type '%s'", self.client_id, msg_type)
        finally:
            log.info("[Client #%d] Cleaning up client session resources", self.client_id)
            self._confirm_result = False
            self._confirm_event.set()
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                log.debug("[Client #%d] Writer close notice: %s", self.client_id, e)

async def main() -> None:
    log.info("Starting Nexus Unix Socket Server (PID: %d)...", os.getpid())
    # Clean up stale socket file if left over from previous process
    if os.path.exists(SOCKET_PATH):
        try:
            log.info("Removing stale socket file at %s", SOCKET_PATH)
            os.unlink(SOCKET_PATH)
        except OSError as e:
            log.warning("Could not unlink %s: %s", SOCKET_PATH, e)

    # Ensure database tables and system instructions are seeded
    log.info("Initializing SQLite context database...")
    context.seed_instructions()

    try:
        server = await asyncio.start_unix_server(
            lambda r, w: ClientHandler(r, w).handle(),
            path=SOCKET_PATH,
        )
    except Exception as e:
        log.critical("Failed to bind Unix domain socket at %s: %s", SOCKET_PATH, e, exc_info=True)
        raise

    try:
        os.chmod(SOCKET_PATH, 0o660)
        log.info("Set socket permissions (0660) on %s", SOCKET_PATH)
    except OSError as e:
        log.warning("Could not set permissions on %s: %s", SOCKET_PATH, e)

    log.info("[socket_server] Successfully listening on %s", SOCKET_PATH)

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Socket server received shutdown signal. Exiting.")
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
                log.info("Unlinked %s on exit", SOCKET_PATH)
            except OSError:
                pass
