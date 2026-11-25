#(©)CodeXBotz




import pymongo, os
from config import (
    DB_URI,
    DB_NAME,
    FORCE_SUB_CHANNEL,
    FORCE_SUB_CHANNEL2,
    FORCE_SUB_CHANNEL_ENABLED,
    FORCE_SUB_CHANNEL2_ENABLED,
)


dbclient = pymongo.MongoClient(DB_URI)
database = dbclient[DB_NAME]


user_data = database['users']
force_subscribe_links = database['force_subscribe_links']



async def present_user(user_id : int):
    found = user_data.find_one({'_id': user_id})
    return bool(found)

async def add_user(user_id: int):
    user_data.insert_one({'_id': user_id})
    return

async def full_userbase():
    user_docs = user_data.find()
    user_ids = []
    for doc in user_docs:
        user_ids.append(doc['_id'])
        
    return user_ids

async def del_user(user_id: int):
    user_data.delete_one({'_id': user_id})
    return


async def get_force_subscriptions():
    """Read the two Railway-controlled FSub channels."""
    return [
        {
            "slot": 1,
            "channel_id": FORCE_SUB_CHANNEL,
            "enabled": FORCE_SUB_CHANNEL_ENABLED,
        },
        {
            "slot": 2,
            "channel_id": FORCE_SUB_CHANNEL2,
            "enabled": FORCE_SUB_CHANNEL2_ENABLED,
        },
    ]


async def get_or_create_force_subscribe_link(slot, channel_id, create_link, link_type="normal"):
    """Reuse one FSub link per configured channel and link type."""
    saved = force_subscribe_links.find_one({
        "slot": slot,
        "channel_id": channel_id,
        "link_type": link_type,
    })
    if saved and saved.get("invite_link"):
        return saved["invite_link"]

    invite_link = await create_link()
    # Pyrogram returns a ChatInviteLink object, while MongoDB and Telegram
    # inline buttons need its URL string.
    invite_link = getattr(invite_link, "invite_link", invite_link)
    if not isinstance(invite_link, str) or not invite_link:
        raise ValueError("The created force-subscribe invite link is invalid")
    force_subscribe_links.update_one(
        {"slot": slot, "channel_id": channel_id, "link_type": link_type},
        {"$set": {"invite_link": invite_link}},
        upsert=True,
    )
    return invite_link


# File-navigation buttons are per Telegram bot ID, even if deployments share MongoDB.
file_button_settings = database["file_button_settings"]
file_button_pending = database["file_button_pending"]


def get_file_button_overrides(bot_id):
    doc = file_button_settings.find_one({"_id": int(bot_id)}, {"links": 1})
    return dict(doc.get("links", {})) if doc else {}


def set_file_button_override(bot_id, button_key, link):
    if button_key not in ("movies", "series", "anime", "tv_index"):
        raise ValueError("Unknown file button.")
    file_button_settings.update_one(
        {"_id": int(bot_id)},
        {"$set": {"links." + button_key: link}},
        upsert=True,
    )


def set_pending_file_button_edit(bot_id, user_id, button_key):
    from datetime import datetime, timedelta, timezone
    if button_key not in ("movies", "series", "anime", "tv_index"):
        raise ValueError("Unknown file button.")
    file_button_pending.update_one(
        {"_id": str(bot_id) + ":" + str(user_id)},
        {"$set": {"button_key": button_key,
                  "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15)}},
        upsert=True,
    )


def get_pending_file_button_edit(bot_id, user_id):
    from datetime import datetime, timezone
    key = str(bot_id) + ":" + str(user_id)
    doc = file_button_pending.find_one({"_id": key})
    if not doc:
        return None
    expires_at = doc.get("expires_at")
    if not expires_at or expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        file_button_pending.delete_one({"_id": key})
        return None
    return doc.get("button_key")


def clear_pending_file_button_edit(bot_id, user_id):
    file_button_pending.delete_one({"_id": str(bot_id) + ":" + str(user_id)})
