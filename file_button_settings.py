"""Configuration and URL validation for file-delivery navigation buttons."""

import re
from urllib.parse import urlsplit

from config import (
    ANIME_BUTTON_LINK,
    ANIME_BUTTON_TEXT,
    MOVIES_BUTTON_LINK,
    MOVIES_BUTTON_TEXT,
    SERIES_BUTTON_LINK,
    SERIES_BUTTON_TEXT,
    TV_SHOW_BUTTON_LINK,
    TV_SHOW_BUTTON_TEXT,
    LOGGER,
)
from database.database import get_file_button_overrides


# Ordered exactly as the recipient sees them: three categories, then index.
BUTTONS = (
    ("movies", MOVIES_BUTTON_TEXT, MOVIES_BUTTON_LINK),
    ("series", SERIES_BUTTON_TEXT, SERIES_BUTTON_LINK),
    ("anime", ANIME_BUTTON_TEXT, ANIME_BUTTON_LINK),
    ("tv_index", TV_SHOW_BUTTON_TEXT, TV_SHOW_BUTTON_LINK),
)
BUTTON_LABELS = {key: label for key, label, _ in BUTTONS}


def normalize_button_url(value):
    """Accept Telegram handles, t.me links or safe HTTPS URLs."""
    if not isinstance(value, str):
        raise ValueError("Send a Telegram channel link as text.")
    link = value.strip()
    if not link or len(link) > 2048 or any(char.isspace() for char in link):
        raise ValueError("Send one valid link without spaces (maximum 2048 characters).")

    if link.startswith("@"):
        if not re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", link):
            raise ValueError("Telegram usernames must be 5-32 letters, digits or underscores.")
        link = "https://t.me/" + link[1:]
    elif link.lower().startswith(("t.me/", "telegram.me/")):
        link = "https://" + link

    try:
        parsed = urlsplit(link)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("That URL is invalid.") from None

    if (
        parsed.scheme != "https"
        or not hostname
        or "." not in hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("Use an HTTPS link such as https://t.me/YourChannel.")

    # These Telegram domains require an invite code, username, or post path.
    if hostname.lower() in ("t.me", "telegram.me") and not parsed.path.strip("/"):
        raise ValueError("Include the channel username or invite code in the link.")
    return link


def get_effective_file_buttons(bot_id, *, safe_fallback=True):
    """Return ordered (key, label, URL) entries using per-bot Mongo overrides.

    An explicit empty-string override hides a button even if Railway has an
    older default. If MongoDB is unavailable during a file send, fall back
    to the Railway defaults rather than breaking delivery.
    """
    overrides = {}
    if bot_id is not None:
        try:
            overrides = get_file_button_overrides(bot_id)
        except Exception:
            if not safe_fallback:
                raise
            LOGGER(__name__).warning(
                "File-button settings unavailable; using Railway defaults."
            )
    return tuple(
        (key, label, overrides.get(key, default_link))
        for key, label, default_link in BUTTONS
    )
