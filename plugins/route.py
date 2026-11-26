import asyncio
import hmac
import os
import re
import secrets
from datetime import datetime, timezone

from aiohttp import web
from pymongo.errors import DuplicateKeyError

routes = web.RouteTableDef()
GWEEN_CLIENT_KEY = web.AppKey("gween_bot_client", object)


@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("Codeflix FileStore")


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


@routes.get("/gween/v1/check", allow_head=False)
async def gween_status_check(request):
    authorized = _gween_authorized(request)
    if authorized is None:
        return _gween_result({"ok": False}, 404)
    if authorized is False:
        return _gween_result({"ok": False}, 401)
    return _gween_result({"ok": True, "protocol": 2, "mode": "season-batches",
        "channel_id": os.environ["CHANNEL_ID"].strip(),
        "autobatch_enabled": os.environ.get("AUTO_BATCH_ENABLED", "False").lower() == "true"})


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
