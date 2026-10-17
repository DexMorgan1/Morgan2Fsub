#(©)CodeFlix_Bots

import asyncio
import base64
import re

import aiohttp
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import Bot
from config import (
    ADMINS,
    AUTO_APPROVE_JOIN_REQUESTS,
    FILE_UPDATE_BUTTONS_ENABLED,
    FORCE_SUB_CHANNEL,
    FORCE_SUB_CHANNEL2,
    FORCE_SUB_CHANNEL_ENABLED,
    FORCE_SUB_CHANNEL2_ENABLED,
    MOVIES_BUTTON_LINK,
    MOVIES_BUTTON_TEXT,
    PROTECT_CONTENT,
    TG_BOT_TOKEN,
    TV_SHOW_BUTTON_LINK,
    TV_SHOW_BUTTON_TEXT,
)
from database.database import get_force_subscriptions


async def is_subscribed(_, client, update):
    """Require membership in every enabled Railway FSub channel."""
    user_id = update.from_user.id
    if user_id in ADMINS:
        return True

    valid_statuses = {
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }
    for channel in await get_force_subscriptions():
        if not channel["enabled"] or not channel["channel_id"]:
            continue
        try:
            member = await client.get_chat_member(channel["channel_id"], user_id)
        except UserNotParticipant:
            return False
        except Exception as error:
            client.LOGGER(__name__).warning(
                "Membership check for channel %s failed: %s", channel["slot"], error,
            )
            return False
        if member.status not in valid_statuses:
            return False
    return True


async def encode(string):
    return base64.urlsafe_b64encode(string.encode("ascii")).decode("ascii").strip("=")


async def decode(base64_string):
    base64_string = base64_string.strip("=")
    return base64.urlsafe_b64decode(
        (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii"),
    ).decode("ascii")


async def get_messages(client, message_ids):
    messages = []
    for offset in range(0, len(message_ids), 200):
        ids = message_ids[offset:offset + 200]
        try:
            fetched = await client.get_messages(client.db_channel.id, ids)
        except FloodWait as error:
            await asyncio.sleep(error.x)
            fetched = await client.get_messages(client.db_channel.id, ids)
        except Exception:
            fetched = []
        messages.extend(fetched)
    return messages


async def get_message_id(client, message):
    if message.forward_from_chat:
        return message.forward_from_message_id if message.forward_from_chat.id == client.db_channel.id else 0
    if message.forward_sender_name:
        return 0
    if message.text:
        matches = re.match(r"https://t.me/(?:c/)?(.*)/(\d+)", message.text)
        if not matches:
            return 0
        channel_id, message_id = matches.groups()
        if channel_id.isdigit() and f"-100{channel_id}" == str(client.db_channel.id):
            return int(message_id)
        if not channel_id.isdigit() and channel_id == client.db_channel.username:
            return int(message_id)
    return 0


def file_update_keyboard(existing_markup=None):
    """Fallback Pyrogram keyboard for the Railway-controlled file buttons."""
    if not FILE_UPDATE_BUTTONS_ENABLED:
        return existing_markup
    rows = [list(row) for row in existing_markup.inline_keyboard] if existing_markup else []
    buttons = []
    if TV_SHOW_BUTTON_LINK:
        buttons.append(InlineKeyboardButton(TV_SHOW_BUTTON_TEXT, url=TV_SHOW_BUTTON_LINK))
    if MOVIES_BUTTON_LINK:
        buttons.append(InlineKeyboardButton(MOVIES_BUTTON_TEXT, url=MOVIES_BUTTON_LINK))
    if buttons:
        rows.append(buttons)
    return InlineKeyboardMarkup(rows) if rows else None


def _button_payload(button):
    payload = {"text": button.text}
    for field in (
        "url", "callback_data", "switch_inline_query",
        "switch_inline_query_current_chat",
    ):
        value = getattr(button, field, None)
        if value is not None:
            payload[field] = value.decode() if isinstance(value, bytes) else value
    return payload


def file_update_button_payload(existing_markup=None):
    """Create solid-blue file buttons for Telegram's Bot API."""
    if not FILE_UPDATE_BUTTONS_ENABLED or not (TV_SHOW_BUTTON_LINK or MOVIES_BUTTON_LINK):
        return None
    rows = []
    if existing_markup:
        rows = [[_button_payload(button) for button in row] for row in existing_markup.inline_keyboard]
    buttons = []
    if TV_SHOW_BUTTON_LINK:
        buttons.append({"text": TV_SHOW_BUTTON_TEXT, "url": TV_SHOW_BUTTON_LINK, "style": "primary"})
    if MOVIES_BUTTON_LINK:
        buttons.append({"text": MOVIES_BUTTON_TEXT, "url": MOVIES_BUTTON_LINK, "style": "primary"})
    rows.append(buttons)
    return {"inline_keyboard": rows}


async def _bot_api_call(method, payload, logger):
    """Use the Bot API styles without exposing or logging the token."""
    if not TG_BOT_TOKEN:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}", json=payload,
            ) as response:
                result = await response.json(content_type=None)
    except Exception as error:
        logger.warning("Telegram Bot API %s request failed: %s", method, error)
        return None
    if result.get("ok"):
        return result.get("result")
    logger.warning(
        "Telegram Bot API %s request was rejected: %s",
        method,
        result.get("description", "unknown error"),
    )
    return None


async def copy_file_with_styled_buttons(client, source_message, chat_id, caption, existing_markup=None):
    """Copy media with styled file buttons, or let the caller use Pyrogram."""
    reply_markup = file_update_button_payload(existing_markup)
    if not reply_markup or not getattr(source_message, "media", None):
        return False
    result = await _bot_api_call(
        "copyMessage",
        {
            "chat_id": chat_id,
            "from_chat_id": source_message.chat.id,
            "message_id": source_message.id,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
            "protect_content": PROTECT_CONTENT,
        },
        client.LOGGER(__name__),
    )
    return result is not None


async def send_force_subscribe_message(client, message, text, buttons):
    """Send blue join buttons on one row, plus a green Try Again button."""
    if not buttons:
        return False
    rows = []
    for row_index, row in enumerate(buttons):
        styled_row = []
        for button in row:
            payload = _button_payload(button)
            payload["style"] = "success" if row_index == len(buttons) - 1 else "primary"
            styled_row.append(payload)
        rows.append(styled_row)
    result = await _bot_api_call(
        "sendMessage",
        {
            "chat_id": message.chat.id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": rows},
            "disable_web_page_preview": True,
        },
        client.LOGGER(__name__),
    )
    return result is not None


@Bot.on_chat_join_request()
async def approve_force_subscribe_request(client, request):
    """Approve join requests only for the two configured request-link channels."""
    configured_channels = {
        FORCE_SUB_CHANNEL if FORCE_SUB_CHANNEL_ENABLED else 0,
        FORCE_SUB_CHANNEL2 if FORCE_SUB_CHANNEL2_ENABLED else 0,
    }
    if not AUTO_APPROVE_JOIN_REQUESTS or request.chat.id not in configured_channels:
        return
    try:
        await client.approve_chat_join_request(request.chat.id, request.from_user.id)
        client.LOGGER(__name__).info("Auto-approved a force-subscribe join request.")
    except Exception as error:
        client.LOGGER(__name__).warning("Could not approve a join request: %s", error)


def get_readable_time(seconds: int) -> str:
    parts = []
    for suffix, unit in (("s", 60), ("m", 60), ("h", 24)):
        seconds, value = divmod(seconds, unit)
        parts.append(f"{value}{suffix}")
    if seconds:
        parts.append(f"{seconds}days")
    return ":".join(reversed(parts))


subscribed = filters.create(is_subscribed)
