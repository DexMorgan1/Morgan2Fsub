#(©)t.me/CodeFlix_Bots




import os
import logging
from logging.handlers import RotatingFileHandler



#Bot token @Botfather
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")

#Your API ID from my.telegram.org
APP_ID = int(os.environ.get("APP_ID", "0"))

#Your API Hash from my.telegram.org
API_HASH = os.environ.get("API_HASH", "")

#Your db channel Id
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))

# NAMA OWNER
OWNER = os.environ.get("OWNER", "")

#OWNER ID
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

#Port
PORT = os.environ.get("PORT", "8030")

#Database
DB_URI = os.environ.get("DATABASE_URL", "")
DB_NAME = os.environ.get("DATABASE_NAME", "Morgan2Fsub")

#force sub channel id, if you want enable force sub
FORCE_SUB_CHANNEL = int(os.environ.get("FORCE_SUB_CHANNEL", os.environ.get("FORCE_SUB_CHANNEL_1", "0")))
FORCE_SUB_CHANNEL2 = int(os.environ.get("FORCE_SUB_CHANNEL2", os.environ.get("FORCE_SUB_CHANNEL_2", "0")))
FORCE_SUB_CHANNEL_ENABLED = os.environ.get("FORCE_SUB_CHANNEL_ENABLED", "True").lower() == "true"
FORCE_SUB_CHANNEL2_ENABLED = os.environ.get("FORCE_SUB_CHANNEL2_ENABLED", "True").lower() == "true"
AUTO_APPROVE_JOIN_REQUESTS = os.environ.get("AUTO_APPROVE_JOIN_REQUESTS", "True").lower() == "true"

TG_BOT_WORKERS = int(os.environ.get("TG_BOT_WORKERS", "4"))

#start message
START_MSG = os.environ.get("START_MESSAGE", "<b>Hello {first}. I store private files for @SeriesAchievers</b>")
try:
    ADMINS = []
    for x in os.environ.get("ADMINS", "").split():
        ADMINS.append(int(x))
except ValueError:
    raise ValueError("ADMINS must be a space-separated list of Telegram numeric IDs.")

#Force sub message 
FORCE_MSG = os.environ.get(
    "FORCE_SUB_MESSAGE",
    "👋 <b>Hello, {first},</b>\n\n"
    "<i>To Receive the requested Files, you must join our two channels below.</i> 👇\n\n"
    "📢 <b>Join, then tap 'Try Again' to access your requested files.</b>",
)

# File update buttons are controlled from Railway. Empty links safely hide
# their corresponding button without requiring a code change.
TV_SHOW_BUTTON_TEXT = os.environ.get("TV_SHOW_BUTTON_TEXT", "📺 TV SHOW").strip() or "📺 TV SHOW"
TV_SHOW_BUTTON_LINK = os.environ.get("TV_SHOW_BUTTON_LINK", "").strip()
MOVIES_BUTTON_TEXT = os.environ.get("MOVIES_BUTTON_TEXT", "🎬 MOVIES").strip() or "🎬 MOVIES"
MOVIES_BUTTON_LINK = os.environ.get("MOVIES_BUTTON_LINK", "").strip()
FILE_UPDATE_BUTTONS_ENABLED = os.environ.get("FILE_UPDATE_BUTTONS_ENABLED", "True").lower() == "true"

#set your Custom Caption here, Keep None for Disable Custom Caption
CUSTOM_CAPTION = os.environ.get("CUSTOM_CAPTION", None)

#set True if you want to prevent users from forwarding files from bot
PROTECT_CONTENT = True if os.environ.get('PROTECT_CONTENT', "False") == "True" else False

#Set true if you want Disable your Channel Posts Share button
DISABLE_CHANNEL_BUTTON = os.environ.get("DISABLE_CHANNEL_BUTTON", None) == 'True'

BOT_STATS_TEXT = "<b>BOT UPTIME</b>\n{uptime}"
USER_REPLY_TEXT = "Pirate ! ʏᴏᴜ Need to be myy Owner to do that !!"

if OWNER_ID:
    ADMINS.append(OWNER_ID)
ADMINS = list(set(ADMINS))

LOG_FILE_NAME = "filesharingbot.txt"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt='%d-%b-%y %H:%M:%S',
    handlers=[
        RotatingFileHandler(
            LOG_FILE_NAME,
            maxBytes=50000000,
            backupCount=10
        ),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)


def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)
   
