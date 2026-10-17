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


async def get_or_create_force_subscribe_link(slot, channel_id, create_link):
    """Reuse one request-to-join link per configured FSub channel."""
    saved = force_subscribe_links.find_one({
        "slot": slot,
        "channel_id": channel_id,
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
        {"slot": slot, "channel_id": channel_id},
        {"$set": {"invite_link": invite_link}},
        upsert=True,
    )
    return invite_link
