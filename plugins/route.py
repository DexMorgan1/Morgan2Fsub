import hmac
import os

from aiohttp import web

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("Codeflix FileStore")

# Read-only health check for the BOT 4 pilot. No Telegram or MongoDB writes.
@routes.get("/gween/v1/check", allow_head=False)
async def gween_status_check(request):
    headers = {"Cache-Control": "no-store"}
    enabled = os.environ.get("GWEEN_STATUS_API_ENABLED", "false").strip().lower() == "true"
    key = os.environ.get("GWEEN_STATUS_API_KEY", "")
    channel = os.environ.get("CHANNEL_ID", "").strip()
    if not enabled or len(key) < 43 or channel != "-1002090847137":
        return web.json_response({"ok": False}, status=404, headers=headers)
    supplied = request.headers.getall("Authorization", [])
    if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode("utf-8"), ("Bearer " + key).encode("utf-8")):
        return web.json_response({"ok": False}, status=401, headers=headers)
    return web.json_response({
        "ok": True,
        "protocol": 1,
        "mode": "status-only",
        "channel_id": channel,
        "autobatch_enabled": os.environ.get("AUTO_BATCH_ENABLED", "False").lower() == "true",
    }, headers=headers)


# Restricted one-show test, not a general batch API. No arbitrary titles or IDs.
# Only the two explicitly authorized test uploads can be linked.
import asyncio
import re
import secrets
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

GWEEN_CLIENT_KEY = web.AppKey("gween_bot_client", object)
_TEST_NAMES = {1: "Gween Test S01E01.mp4", 2: "Gween Test S01E02.mp4"}
_TEST_CHANNEL = -1002090847137


def _test_filename(name):
    # Normalize the extension only; the authorized test title stays exact.
    if isinstance(name, str) and name[-4:].lower() == ".mp4":
        return name[:-4] + ".mp4"
    return None


@routes.post("/gween/v1/test-batch")
async def gween_test_batch(request):
    def result(payload, status=200):
        return web.json_response(payload, status=status, headers={"Cache-Control": "no-store"})

    key = os.environ.get("GWEEN_STATUS_API_KEY", "")
    if (os.environ.get("GWEEN_STATUS_API_ENABLED", "false").strip().lower() != "true"
            or len(key) < 43 or os.environ.get("CHANNEL_ID", "").strip() != str(_TEST_CHANNEL)):
        return result({"ok": False}, 404)
    supplied = request.headers.getall("Authorization", [])
    if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode("utf-8"), ("Bearer " + key).encode("utf-8")):
        return result({"ok": False}, 401)
    if request.query_string or request.can_read_body:
        return result({"ok": False, "reason": "unexpected_input"}, 400)
    client = request.app.get(GWEEN_CLIENT_KEY)
    if (not client or (getattr(client, "username", "") or "").lower() != "seriesachieverhdbot"
            or getattr(getattr(client, "db_channel", None), "id", None) != _TEST_CHANNEL):
        return result({"ok": False, "reason": "bot_not_ready"}, 503)

    try:
        from plugins import autobatch as ab
        if not ab.ENABLED:
            return result({"ok": False, "reason": "autobatch_disabled"}, 409)

        # Fixed message IDs supplied by the admin for this one pilot.
        # Do not search or alter the AutoBatch index or any other files.
        approved_ids = [7354, 7355]
        originals = await asyncio.wait_for(
            client.get_messages(_TEST_CHANNEL, approved_ids, replies=0), timeout=15
        )
        if not isinstance(originals, list) or len(originals) != 2:
            return result({"ok": False, "reason": "test_files_not_found"}, 409)
        verified = {}
        for message in originals:
            if (not message or getattr(message, "empty", False)
                    or getattr(getattr(message, "chat", None), "id", None) != _TEST_CHANNEL
                    or message.id not in approved_ids or message.id in verified):
                return result({"ok": False, "reason": "test_files_not_found"}, 409)
            media = message.video or message.document
            filename = _test_filename(getattr(media, "file_name", None))
            size = getattr(media, "file_size", None)
            if (filename not in _TEST_NAMES.values() or not isinstance(size, int)
                    or not 0 < size <= 5 * 1024 * 1024):
                return result({"ok": False, "reason": "test_filename_mismatch"}, 409)
            verified[message.id] = filename
        if set(verified) != set(approved_ids) or set(verified.values()) != set(_TEST_NAMES.values()):
            return result({"ok": False, "reason": "test_filename_mismatch"}, 409)
        ids = [next(mid for mid, name in verified.items() if name == _TEST_NAMES[ep]) for ep in (1, 2)]

        # An isolated pilot identity cannot collide with parser-generated IDs
        # or be expanded automatically when new channel files are indexed.
        scope = {"channel_id": _TEST_CHANNEL, "series_id": "gween-test-7354-7355"}
        ab.ensure_indexes()
        batch_scope = dict(scope, season=1)
        if not ab.links.find_one(batch_scope):
            try:
                ab.links.insert_one(dict(batch_scope, token=secrets.token_urlsafe(18),
                    message_ids=ids, updated_at=datetime.now(timezone.utc), series_title="Gween Test"))
            except DuplicateKeyError:
                pass
        saved = ab.links.find_one(batch_scope)
        if (not saved or saved.get("message_ids") != ids or saved.get("series_title") != "Gween Test"
                or not re.fullmatch(r"[A-Za-z0-9_-]{24}", saved.get("token") or "")):
            return result({"ok": False, "reason": "existing_test_batch_conflict"}, 409)
        client.LOGGER(__name__).info("Gween test batch verified: two original test files; no media copied.")
        return result({"ok": True, "title": "Gween Test", "season": 1, "episodes": 2,
            "channel_id": str(_TEST_CHANNEL), "batch_url": "https://t.me/SeriesAchieverHDBOT?start=ab_" + saved["token"]})
    except Exception:
        client.LOGGER(__name__).warning("Gween test batch failed (details redacted).")
        return result({"ok": False, "reason": "test_check_failed"}, 503)
