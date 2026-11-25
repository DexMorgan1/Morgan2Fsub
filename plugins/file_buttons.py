"""Private admin controls for file-delivery navigation buttons."""

from html import escape

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import Bot
from config import ADMINS
from database.database import (
    clear_pending_file_button_edit,
    get_pending_file_button_edit,
    set_file_button_override,
    set_pending_file_button_edit,
)
from file_button_settings import BUTTON_LABELS, get_effective_file_buttons, normalize_button_url


def bot_id(client):
    return client.bot_user_id


def menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Movies", callback_data="fb:edit:movies"),
         InlineKeyboardButton("📺 Series", callback_data="fb:edit:series")],
        [InlineKeyboardButton("🎌 Anime", callback_data="fb:edit:anime")],
        [InlineKeyboardButton("📚 TV/WEB Series Index", callback_data="fb:edit:tv_index")],
        [InlineKeyboardButton("👁 Preview", callback_data="fb:preview"),
         InlineKeyboardButton("✖ Close", callback_data="fb:close")],
    ])


def menu_text(client):
    buttons = get_effective_file_buttons(bot_id(client), safe_fallback=False)
    lines = ["<b>File Button Settings</b>", "",
             "Select a button to set or remove its link:", ""]
    for _, label, url in buttons:
        lines.append("• <b>" + escape(label) + "</b>: " +
                     ("Configured ✅" if url else "Not configured"))
    lines.extend(["", "Changes affect future file deliveries only."])
    return "\n".join(lines)


def preview_markup(client):
    buttons = get_effective_file_buttons(bot_id(client), safe_fallback=False)
    rows = []
    row = [InlineKeyboardButton(label, url=url) for key, label, url in buttons
           if key != "tv_index" and url]
    if row:
        rows.append(row)
    index = next(((label, url) for key, label, url in buttons if key == "tv_index"), None)
    if index and index[1]:
        rows.append([InlineKeyboardButton(index[0], url=index[1])])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="fb:back")])
    return InlineKeyboardMarkup(rows)


@Bot.on_message(filters.private & filters.command("buttons") & filters.user(ADMINS), group=-2)
async def buttons_command(client, message):
    try:
        clear_pending_file_button_edit(bot_id(client), message.from_user.id)
        await message.reply_text(menu_text(client), reply_markup=menu_markup())
    except Exception:
        client.LOGGER(__name__).exception("Unable to open file-button settings")
        await message.reply_text("Unable to load button settings. Please try again.")
    message.stop_propagation()


@Bot.on_callback_query(filters.regex(r"^fb:(edit:(movies|series|anime|tv_index)|preview|back|clear:(movies|series|anime|tv_index)|close)$"), group=-1)
async def button_menu_callback(client, query):
    if query.from_user.id not in ADMINS or query.message.chat.type.value != "private":
        await query.answer("Only authorized admins can use this menu.", show_alert=True)
        query.stop_propagation()
        return

    action = query.data.split(":")
    try:
        if action[1] == "edit":
            key = action[2]
            set_pending_file_button_edit(bot_id(client), query.from_user.id, key)
            await query.message.edit_text(
                "<b>Set " + escape(BUTTON_LABELS[key]) + " link</b>\n\n"
                "Send a Telegram channel username (e.g. @MyChannel), "
                "a t.me invitation link, or an HTTPS URL in this chat.\n\n"
                "You have 15 minutes to send it.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 Remove link", callback_data="fb:clear:" + key)],
                    [InlineKeyboardButton("⬅ Back", callback_data="fb:back")],
                ]),
            )
        elif action[1] == "clear":
            key = action[2]
            set_file_button_override(bot_id(client), key, "")
            clear_pending_file_button_edit(bot_id(client), query.from_user.id)
            await query.message.edit_text(menu_text(client), reply_markup=menu_markup())
        elif action[1] == "preview":
            clear_pending_file_button_edit(bot_id(client), query.from_user.id)
            await query.message.edit_text(
                "<b>File button preview</b>\n\n"
                "This is what configured buttons look like on a delivered file. "
                "Buttons without links will not appear.",
                reply_markup=preview_markup(client),
            )
        elif action[1] == "back":
            clear_pending_file_button_edit(bot_id(client), query.from_user.id)
            await query.message.edit_text(menu_text(client), reply_markup=menu_markup())
        elif action[1] == "close":
            clear_pending_file_button_edit(bot_id(client), query.from_user.id)
            await query.message.delete()
        await query.answer()
    except Exception:
        client.LOGGER(__name__).exception("Unable to change Telegram file-button settings")
        await query.answer("Couldn't save settings. Try again.", show_alert=True)
    query.stop_propagation()


@Bot.on_message(filters.private & filters.text & filters.user(ADMINS) & ~filters.command("buttons"), group=-1)
async def receive_button_link(client, message):
    try:
        key = get_pending_file_button_edit(bot_id(client), message.from_user.id)
    except Exception:
        client.LOGGER(__name__).exception("Could not read pending button edit")
        # Reply first: Pyrogram stop_propagation raises immediately.
        await message.reply_text("Settings unavailable. Please send /buttons again.")
        message.stop_propagation()
        return

    if not key:
        # Normal messages must still reach existing file-store handlers.
        return

    try:
        if message.text.strip().lower() == "/cancel":
            clear_pending_file_button_edit(bot_id(client), message.from_user.id)
            await message.reply_text("Cancelled.", reply_markup=menu_markup())
        else:
            try:
                link = normalize_button_url(message.text)
            except ValueError as exc:
                await message.reply_text(escape(str(exc)) + "\nSend a valid link or /cancel.")
            else:
                try:
                    set_file_button_override(bot_id(client), key, link)
                    clear_pending_file_button_edit(bot_id(client), message.from_user.id)
                    await message.reply_text(
                        "✅ <b>" + escape(BUTTON_LABELS[key]) + "</b> updated.\n\n" +
                        menu_text(client), reply_markup=menu_markup(),
                    )
                except Exception:
                    client.LOGGER(__name__).exception("Could not save button destination")
                    await message.reply_text("Could not save this link. Please try again.")
    finally:
        # Avoid treating link messages as database uploads, but only after
        # the bot has saved the URL and sent its confirmation or error.
        message.stop_propagation()
