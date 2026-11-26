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


# One-shot, fixed-record integration for Gween's openly licensed Caminandes pilot.
# It accepts no identifiers or request body, never scans or posts media, and keeps a
# stable token if a prior successful call already created the same batch.
_CAMINANDES_MESSAGE_ID = 7358
_CAMINANDES_SERIES_ID = "gween-caminandes-7358"
_CAMINANDES_TITLE = "Caminandes (2013) — S01E01 — Llama Drama"
_CAMINANDES_CREDIT_MARKERS = (
    "CC BY 3.0",
    "https://creativecommons.org/licenses/by/3.0/",
    "https://commons.wikimedia.org/wiki/File:Caminandes-_Llama_Drama_-_Short_Movie.ogv",
)


@routes.post("/gween/v1/caminandes-batch")
async def gween_caminandes_batch(request):
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
        original = await asyncio.wait_for(
            client.get_messages(_TEST_CHANNEL, _CAMINANDES_MESSAGE_ID, replies=0), timeout=15
        )
        if isinstance(original, list):
            original = original[0] if original else None
        media = (getattr(original, "video", None) or getattr(original, "document", None)) if original else None
        caption = getattr(original, "caption", "") or ""
        if (not original or getattr(original, "empty", False)
                or getattr(getattr(original, "chat", None), "id", None) != _TEST_CHANNEL
                or getattr(original, "id", None) != _CAMINANDES_MESSAGE_ID or not media
                or _CAMINANDES_TITLE not in caption
                or any(marker not in caption for marker in _CAMINANDES_CREDIT_MARKERS)):
            return result({"ok": False, "reason": "caminandes_record_mismatch"}, 409)
        ab.ensure_indexes()
        scope = {"channel_id": _TEST_CHANNEL, "series_id": _CAMINANDES_SERIES_ID, "season": 1}
        saved = ab.links.find_one(scope)
        if saved and saved.get("message_ids") != [_CAMINANDES_MESSAGE_ID]:
            return result({"ok": False, "reason": "existing_caminandes_batch_conflict"}, 409)
        if not saved:
            try:
                ab.links.insert_one(dict(scope, token=secrets.token_urlsafe(18),
                    message_ids=[_CAMINANDES_MESSAGE_ID], updated_at=datetime.now(timezone.utc),
                    series_title="Caminandes (2013)"))
            except DuplicateKeyError:
                pass
        saved = ab.links.find_one(scope)
        if (not saved or saved.get("message_ids") != [_CAMINANDES_MESSAGE_ID]
                or saved.get("series_title") != "Caminandes (2013)"
                or not re.fullmatch(r"[A-Za-z0-9_-]{24}", saved.get("token") or "")):
            return result({"ok": False, "reason": "caminandes_batch_conflict"}, 409)
        client.LOGGER(__name__).info("Gween Caminandes batch verified: original message 7358; no media copied.")
        return result({"ok": True, "title": "Caminandes (2013)", "season": 1, "episodes": 1,
            "channel_id": str(_TEST_CHANNEL), "message_id": _CAMINANDES_MESSAGE_ID,
            "batch_url": "https://t.me/SeriesAchieverHDBOT?start=ab_" + saved["token"]})
    except Exception:
        client.LOGGER(__name__).warning("Gween Caminandes batch failed (details redacted).")
        return result({"ok": False, "reason": "caminandes_check_failed"}, 503)


# BOT 4 retains its fixed Caminandes endpoint above; this generic endpoint is additive.
def _gween_result(payload, status=200):
    return web.json_response(payload, status=status, headers={"Cache-Control": "no-store"})


def _gween_authorized(request):
    key = os.environ.get("GWEEN_STATUS_API_KEY", "")
    channel = os.environ.get("CHANNEL_ID", "").strip()
    if os.environ.get("GWEEN_STATUS_API_ENABLED", "false").strip().lower() != "true" or len(key) < 43 or not re.fullmatch(r"-100\d+", channel):
        return None
    supplied = request.headers.getall("Authorization", [])
    if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode(), ("Bearer " + key).encode()):
        return False
    return key




# Secure, explicit manifest API. It never discovers, downloads, copies, edits, or
# publishes media. It only builds stable batch records for already-present messages.
@routes.post("/gween/v1/season-batches")
async def gween_season_batches(request):
    authorized = _gween_authorized(request)
    if authorized is None:
        return _gween_result({"ok": False}, 404)
    if authorized is False:
        return _gween_result({"ok": False}, 401)
    if request.query_string:
        return _gween_result({"ok": False, "reason": "unexpected_query"}, 400)
    try:
        body = await request.json()
    except Exception:
        return _gween_result({"ok": False, "reason": "invalid_json"}, 400)
    if not isinstance(body, dict) or set(body) != {"series_key", "title", "credit_marker", "seasons"}:
        return _gween_result({"ok": False, "reason": "invalid_manifest"}, 400)
    series_key, title, credit_marker, seasons = body["series_key"], body["title"], body["credit_marker"], body["seasons"]
    if (not isinstance(series_key, str) or not re.fullmatch(r"gween-[a-z0-9-]{3,80}", series_key)
            or not isinstance(title, str) or not 1 <= len(title) <= 160
            or not isinstance(credit_marker, str) or not 3 <= len(credit_marker) <= 120
            or not isinstance(seasons, list) or not 1 <= len(seasons) <= 20):
        return _gween_result({"ok": False, "reason": "invalid_manifest"}, 400)
    client = request.app.get(GWEEN_CLIENT_KEY)
    channel_id = int(os.environ["CHANNEL_ID"])
    if (not client or not getattr(client, "username", None)
            or getattr(getattr(client, "db_channel", None), "id", None) != channel_id):
        return _gween_result({"ok": False, "reason": "bot_not_ready"}, 503)
    try:
        from plugins import autobatch as ab
        if not ab.ENABLED:
            return _gween_result({"ok": False, "reason": "autobatch_disabled"}, 409)
        normalized, seen_ids, seen_seasons = [], set(), set()
        for item in seasons:
            if not isinstance(item, dict) or set(item) != {"season", "expected", "episodes"}:
                return _gween_result({"ok": False, "reason": "invalid_manifest"}, 400)
            season, expected, episodes = item["season"], item["expected"], item["episodes"]
            if (not isinstance(season, int) or not 1 <= season <= 99 or season in seen_seasons
                    or not isinstance(expected, int) or not 1 <= expected <= 999
                    or not isinstance(episodes, list) or len(episodes) != expected):
                return _gween_result({"ok": False, "reason": "incomplete_season"}, 409)
            seen_seasons.add(season)
            episode_numbers, ids = [], []
            for episode in episodes:
                if not isinstance(episode, dict) or set(episode) != {"episode", "message_id"}:
                    return _gween_result({"ok": False, "reason": "invalid_manifest"}, 400)
                number, message_id = episode["episode"], episode["message_id"]
                if (not isinstance(number, int) or not 1 <= number <= 999
                        or not isinstance(message_id, int) or message_id <= 0
                        or number in episode_numbers or message_id in seen_ids):
                    return _gween_result({"ok": False, "reason": "duplicate_episode"}, 409)
                episode_numbers.append(number); ids.append(message_id); seen_ids.add(message_id)
            if sorted(episode_numbers) != list(range(1, expected + 1)):
                return _gween_result({"ok": False, "reason": "incomplete_season"}, 409)
            normalized.append((season, expected, [mid for _, mid in sorted(zip(episode_numbers, ids))]))
        all_ids = [message_id for _, _, ids in normalized for message_id in ids]
        originals = await asyncio.wait_for(client.get_messages(channel_id, all_ids, replies=0), timeout=30)
        if not isinstance(originals, list) or len(originals) != len(all_ids):
            return _gween_result({"ok": False, "reason": "source_missing"}, 409)
        found = {getattr(message, "id", None): message for message in originals if message and not getattr(message, "empty", False)}
        if set(found) != set(all_ids):
            return _gween_result({"ok": False, "reason": "source_missing"}, 409)
        for message_id in all_ids:
            message = found[message_id]
            if (getattr(getattr(message, "chat", None), "id", None) != channel_id
                    or not (getattr(message, "video", None) or getattr(message, "document", None))
                    or credit_marker not in (getattr(message, "caption", "") or "")):
                return _gween_result({"ok": False, "reason": "source_mismatch"}, 409)
        ab.ensure_indexes()
        links = []
        for season, expected, ids in normalized:
            scope = {"channel_id": channel_id, "series_id": series_key, "season": season}
            saved = ab.links.find_one(scope)
            if saved and saved.get("message_ids") != ids:
                return _gween_result({"ok": False, "reason": "existing_batch_conflict"}, 409)
            if not saved:
                try:
                    ab.links.insert_one(dict(scope, token=secrets.token_urlsafe(18), message_ids=ids,
                        updated_at=datetime.now(timezone.utc), series_title=title))
                except DuplicateKeyError:
                    pass
            saved = ab.links.find_one(scope)
            if not saved or saved.get("message_ids") != ids or not re.fullmatch(r"[A-Za-z0-9_-]{24}", saved.get("token") or ""):
                return _gween_result({"ok": False, "reason": "batch_write_failed"}, 503)
            links.append({"season": season, "episodes": expected,
                "batch_url": "https://t.me/%s?start=ab_%s" % (client.username, saved["token"])})
        client.LOGGER(__name__).info("Gween season-batch manifest verified: %s seasons, %s original messages; no media copied.", len(links), len(all_ids))
        return _gween_result({"ok": True, "protocol": 2, "channel_id": str(channel_id),
            "series_key": series_key, "links": links})
    except Exception:
        client.LOGGER(__name__).warning("Gween season-batch manifest failed (details redacted).")
        return _gween_result({"ok": False, "reason": "batch_check_failed"}, 503)
