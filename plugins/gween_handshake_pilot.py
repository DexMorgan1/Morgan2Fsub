"""Private Gween handshake pilot. No file, batch, or database operations."""
import os
import re
import time

from pyrogram import Client, filters
from bot import Bot

_ENABLED = os.environ.get("GWEEN_HANDSHAKE_ENABLED", "false").strip().lower() == "true"
_TARGET = "seriesachieverhdbot"
_SENDER = "gweensyncshowsai"
_PATTERN = re.compile(r"^/gweenping ([0-9a-f]{32})$")
_last_probe = None


@Bot.on_message(filters.private & filters.bot & filters.regex(_PATTERN.pattern), group=-10)
async def gween_private_probe(client: Client, message):
    global _last_probe
    try:
        sender = getattr(message, "from_user", None)
        chat = getattr(message, "chat", None)
        match = _PATTERN.fullmatch(message.text or "")
        if not (
            _ENABLED
            and (getattr(client, "username", "") or "").lower() == _TARGET
            and sender and sender.is_bot
            and (sender.username or "").lower() == _SENDER
            and chat and chat.id == sender.id
            and match
        ):
            return
        now = time.monotonic()
        if _last_probe is not None and (now - _last_probe[0] < 60 or _last_probe[1] == match[1]):
            return
        _last_probe = (now, match[1])
        try:
            await client.send_message(chat.id, "GWEEN_PONG " + match[1])
            client.LOGGER(__name__).info("Gween private handshake replied (no file operations).")
        except Exception:
            client.LOGGER(__name__).warning("Gween private handshake reply failed (details redacted).")
    finally:
        message.stop_propagation()
