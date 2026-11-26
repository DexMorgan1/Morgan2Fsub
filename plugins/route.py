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
