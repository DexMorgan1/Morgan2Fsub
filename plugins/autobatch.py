"""Optional, admin-only auto season batching for the existing FSub bot.

Stores references to original DATABASE messages; never reposts, moves,
removes, or edits channel files. The original /batch remains untouched.
"""
import asyncio
import html
import os
import secrets
from datetime import datetime, timezone

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from autobatch_core import organize_seasons, parse_media
from bot import Bot
from config import ADMINS, CHANNEL_ID, CUSTOM_CAPTION, PROTECT_CONTENT, DISABLE_CHANNEL_BUTTON
from database.database import database
from helper_func import copy_file_with_styled_buttons, file_update_keyboard, get_messages

ENABLED = os.environ.get("AUTO_BATCH_ENABLED", "False").lower() == "true"
MAX_SCAN = 1000
PAGE_SIZE = 8
files = database["auto_batch_files"]
links = database["auto_batch_links"]
_indexes_ready = False


def ensure_indexes():
    global _indexes_ready
    if _indexes_ready:
        return
    files.create_index([("channel_id", 1), ("message_id", 1)], unique=True)
    files.create_index([("channel_id", 1), ("series_id", 1), ("season", 1)])
    links.create_index("token", unique=True)
    links.create_index([("channel_id", 1), ("series_id", 1), ("season", 1)], unique=True)
    _indexes_ready = True


def record_file(message):
    """Index only relevant documents/videos and reliable title matches."""
    media = message.video or message.document
    if not media or not getattr(message, "id", None) or message.id <= 0:
        return False
    filename = getattr(media, "file_name", "") or ""
    parsed = parse_media(filename, message.caption or "", is_video=bool(message.video))
    if not parsed:
        return False
    ensure_indexes()
    document = dict(parsed)
    document.update({
        "channel_id": CHANNEL_ID,
        "message_id": message.id,
        "file_name": filename[:300],
        "indexed_at": datetime.now(timezone.utc),
    })
    files.update_one(
        {"channel_id": CHANNEL_ID, "message_id": message.id},
        {"$set": document},
        upsert=True,
    )
    # Existing season links must include any newly indexed episodes. Keep
    # their tokens stable, so previously shared links continue working.
    filter_key = {"channel_id": CHANNEL_ID, "series_id": document["series_id"], "season": document["season"]}
    existing_link = links.find_one(filter_key)
    if existing_link:
        records = list(files.find({"channel_id": CHANNEL_ID, "series_id": document["series_id"], "season": document["season"]}))
        seasons = organize_seasons(records)
        selection = next((row for row in seasons if row["season"] == document["season"]), None)
        if selection:
            links.update_one(filter_key, {"$set": {
                "message_ids": selection["message_ids"],
                "updated_at": datetime.now(timezone.utc),
                "series_title": document["series_title"],
            }})
    return True


def list_series():
    ensure_indexes()
    return list(files.aggregate([
        {"$match": {"channel_id": CHANNEL_ID, "series_id": {"$exists": True}}},
        {"$group": {"_id": "$series_id", "title": {"$first": "$series_title"}, "count": {"$sum": 1}}},
        {"$sort": {"title": 1}},
    ]))


def get_series(series_id):
    ensure_indexes()
    rows = list(files.find({"channel_id": CHANNEL_ID, "series_id": series_id}).sort("message_id", 1))
    if not rows:
        return None, []
    return rows[0].get("series_title", "Series"), organize_seasons(rows)


def _button_list(page=0, query=""):
    all_rows = list_series()
    if query:
        all_rows = [item for item in all_rows if query.casefold() in item["title"].casefold()]
    if not all_rows:
        return "No matching series indexed yet. Use /scanbatch for older files.", None
    max_page = (len(all_rows) - 1) // PAGE_SIZE
    page = min(max(0, page), max_page)
    subset = all_rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [[InlineKeyboardButton(
        "%s (%s files)" % (item["title"][:34], item["count"]),
        callback_data="ab:pick:%s" % item["_id"],
    )] for item in subset]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("Previous", callback_data="ab:list:%s" % (page - 1)))
    if page < max_page:
        nav.append(InlineKeyboardButton("Next", callback_data="ab:list:%s" % (page + 1)))
    if nav:
        rows.append(nav)
    caption = "<b>AUTO BATCH</b>\nSelect one series (%s total, page %s/%s)." % (len(all_rows), page + 1, max_page + 1)
    return caption, InlineKeyboardMarkup(rows)


def _preview(series_id):
    title, seasons = get_series(series_id)
    if not seasons:
        return "This series has no matching episodes.", None
    parts = ["<b>%s</b>", "", "One link will be created for each season:"]
    for season in seasons:
        note = ""
        if season["missing"]:
            note += " | gaps: %s" % ", ".join(str(x) for x in season["missing"][:15])
        if season["duplicates"]:
            note += " | %s duplicate(s) skipped" % season["duplicates"]
        parts.append("SEASON %s - %s episode(s)%s" % (season["season"], season["episodes"], note))
    parts.extend(["", "Please check the season counts and any gaps. Only confirmed episodes will be linked."])
    text = "\n".join(parts) % html.escape(title)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Create season batch links", callback_data="ab:make:%s" % series_id)],
        [InlineKeyboardButton("Back to list", callback_data="ab:list:0")],
    ])
    return text[:4000], buttons


def create_season_links(client, series_id):
    title, seasons = get_series(series_id)
    if not seasons:
        return None
    out = ["<b>%s</b>", ""]
    for season in seasons:
        filter_key = {"channel_id": CHANNEL_ID, "series_id": series_id, "season": season["season"]}
        existing = links.find_one(filter_key)
        token = existing.get("token") if existing else secrets.token_urlsafe(18)
        # Keep generated URLs stable when episodes are added later.
        links.update_one(filter_key, {"$set": {
            "token": token,
            "message_ids": season["message_ids"],
            "updated_at": datetime.now(timezone.utc),
            "series_title": title,
        }}, upsert=True)
        deep_link = "https://t.me/%s?start=ab_%s" % (client.username, token)
        out.append("<b>SEASON %s</b> - %s" % (season["season"], deep_link))
    out.append("\nFiles remain in the original DATABASE channel.")
    return ("\n".join(out) % html.escape(title))[:4096]


@Bot.on_message(filters.channel & filters.incoming & filters.chat(CHANNEL_ID), group=1)
async def auto_index_new_posts(client: Client, message):
    if not ENABLED:
        return
    try:
        record_file(message)
    except Exception as error:
        client.LOGGER(__name__).warning("AutoBatch indexing failed: %s", error)


@Bot.on_message(filters.private & filters.user(ADMINS) & filters.command("scanbatch"))
async def scanbatch(client: Client, message):
    if not ENABLED:
        await message.reply_text("AutoBatch is disabled on this bot.")
        return
    try:
        start, end = map(int, message.command[1:3])
        assert 0 < start <= end and end - start + 1 <= MAX_SCAN
    except (ValueError, AssertionError):
        await message.reply_text("Use /scanbatch FIRST_ID LAST_ID (up to 1000 channel posts per scan).\nExample: /scanbatch 1 500")
        return
    progress = await message.reply_text("Checking old DATABASE messages %s to %s. Nothing will be forwarded." % (start, end))
    found, count, unrecognized_media = 0, 0, 0
    try:
        for beginning in range(start, end + 1, 200):
            message_ids = list(range(beginning, min(end + 1, beginning + 200)))
            try:
                retrieved = await client.get_messages(client.db_channel.id, message_ids, replies=0)
            except FloodWait as error:
                await asyncio.sleep(error.x)
                retrieved = await client.get_messages(client.db_channel.id, message_ids, replies=0)
            for old_message in retrieved or []:
                if not old_message or getattr(old_message, "empty", False):
                    continue
                count += 1
                if record_file(old_message):
                    found += 1
                elif old_message.video or old_message.document:
                    unrecognized_media += 1
    except Exception as error:
        client.LOGGER(__name__).warning("AutoBatch old-message scan failed: %s", error)
        await progress.edit_text("Scan stopped. Check bot access to DATABASE and try a smaller ID range. No files were changed.")
        return
    await progress.edit_text(
        "Scan complete: checked %s messages, recognized %s episodes, "
        "and skipped %s files with unrecognized names. "
        "Send /autobatch to view the indexed shows."
        % (count, found, unrecognized_media)
    )


@Bot.on_message(filters.private & filters.user(ADMINS) & filters.command("autobatch"))
async def autobatch(client: Client, message):
    if not ENABLED:
        await message.reply_text("AutoBatch is disabled on this bot.")
        return
    try:
        query = " ".join(message.command[1:]).strip()
        text, buttons = _button_list(query=query)
    except Exception as error:
        client.LOGGER(__name__).warning("AutoBatch catalog failed: %s", error)
        await message.reply_text("Cannot read the AutoBatch index. Please try again.")
        return
    await message.reply_text(text, reply_markup=buttons)


@Bot.on_callback_query(filters.regex(r"^ab:"))
async def autobatch_callback(client: Client, callback):
    if not ENABLED or callback.from_user.id not in ADMINS:
        await callback.answer("Admins only", show_alert=True)
        return
    data = (callback.data or "").split(":", 2)
    if len(data) != 3:
        await callback.answer("Invalid selection")
        return
    action, key = data[1:]
    try:
        if action == "list":
            text, buttons = _button_list(page=int(key))
        elif action == "pick":
            text, buttons = _preview(key)
        elif action == "make":
            text = create_season_links(client, key)
            buttons = None
            if not text:
                text = "Series not found. Send /autobatch to refresh the list."
        else:
            await callback.answer("Unknown action")
            return
        await callback.message.edit_text(text, reply_markup=buttons, disable_web_page_preview=True)
        await callback.answer("Ready")
    except Exception as error:
        client.LOGGER(__name__).warning("AutoBatch action failed: %s", error)
        await callback.answer("Could not complete this action", show_alert=True)


async def deliver_auto_batch(client, message, token):
    """Called inside existing /start subscribed handler. Only read original media."""
    if not ENABLED:
        await message.reply_text("This AutoBatch link is not active on this bot.")
        return
    record = links.find_one({"token": token, "channel_id": client.db_channel.id})
    if not record:
        await message.reply_text("This batch link was not found.")
        return
    message_ids = record.get("message_ids") or []
    if not message_ids:
        await message.reply_text("This batch has no stored episodes.")
        return
    status = await message.reply_text("Sending %s - Season %s (%s episodes)." % (
        html.escape(record.get("series_title", "Series")),
        record.get("season", "?"),
        len(message_ids),
    ))
    try:
        messages = await get_messages(client, message_ids)
    except Exception as error:
        client.LOGGER(__name__).warning("AutoBatch delivery fetch failed: %s", error)
        await status.edit_text("Could not retrieve this batch from DATABASE.")
        return
    delivered = 0
    for media in messages:
        if not media or getattr(media, "empty", False) or not (media.video or media.document):
            continue
        if CUSTOM_CAPTION and media.document:
            caption = CUSTOM_CAPTION.format(
                previouscaption="" if not media.caption else media.caption.html,
                filename=media.document.file_name,
            )
        else:
            caption = "" if not media.caption else media.caption.html
        source_markup = media.reply_markup if DISABLE_CHANNEL_BUTTON else None
        reply_markup = file_update_keyboard(source_markup)
        try:
            copied = await copy_file_with_styled_buttons(
                client, media, message.from_user.id, caption, source_markup,
            )
            if not copied:
                await media.copy(chat_id=message.from_user.id, caption=caption,
                                 parse_mode=ParseMode.HTML, reply_markup=reply_markup,
                                 protect_content=PROTECT_CONTENT)
            delivered += 1
            await asyncio.sleep(0.5)
        except FloodWait as error:
            await asyncio.sleep(error.x)
            try:
                await media.copy(chat_id=message.from_user.id, caption=caption,
                                 parse_mode=ParseMode.HTML, reply_markup=reply_markup,
                                 protect_content=PROTECT_CONTENT)
                delivered += 1
            except Exception:
                client.LOGGER(__name__).warning("AutoBatch file copy failed after retry")
        except Exception as error:
            client.LOGGER(__name__).warning("AutoBatch file copy failed: %s", error)
    await status.edit_text("Sent %s/%s episodes for %s - Season %s." % (
        delivered, len(message_ids), html.escape(record.get("series_title", "Series")), record.get("season", "?"),
    ))
