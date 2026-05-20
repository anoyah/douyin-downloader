#!/usr/bin/env python3
"""
RESTful HTTP 服务。

端点：
  GET /api/resolve?url=<抖音链接或分享文案>
      → JSON { code, message, data: { title, url } }

  GET /proxy?url=<抖音链接或分享文案>
      → 流式视频（video/mp4，Content-Disposition: attachment）

启动：python server.py [port]   （默认 8080）
"""
import json
import re
import sys
from typing import Dict, Tuple
from urllib.parse import quote

import aiohttp
from aiohttp import web

from auth import CookieManager
from config import ConfigLoader
from control import QueueManager, RateLimiter, RetryHandler
from core import DouyinAPIClient, URLParser
from core.video_downloader import VideoDownloader
from storage import FileManager
from utils.validators import extract_douyin_url, is_short_url, normalize_short_url

CHUNK_SIZE = 256 * 1024  # 256 KB

# ── 跨域（开发期允许所有来源） ────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _json(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        headers=CORS_HEADERS,
        text=json.dumps(data, ensure_ascii=False),
    )


def _ok(data: dict) -> web.Response:
    return _json({"code": 0, "message": "ok", "data": data})


def _err(message: str, status: int = 422) -> web.Response:
    return _json({"code": 1, "message": message, "data": None}, status=status)


# ── 内部工具 ─────────────────────────────────────────────────────────────
def _make_downloader(app: web.Application) -> VideoDownloader:
    return VideoDownloader(
        config=app["config"],
        api_client=app["api_client"],
        file_manager=app["file_manager"],
        cookie_manager=app["cookie_manager"],
        database=None,
        rate_limiter=RateLimiter(),
        retry_handler=RetryHandler(),
        queue_manager=QueueManager(max_workers=1),
    )


async def _resolve(raw: str, app: web.Application) -> Tuple[str, Dict[str, str], str]:
    """从原始文本解析出 (video_url, cdn_headers, title)。"""
    url = extract_douyin_url(raw) or raw
    api_client: DouyinAPIClient = app["api_client"]

    if is_short_url(url):
        resolved = await api_client.resolve_short_url(normalize_short_url(url))
        if not resolved:
            raise ValueError("短链解析失败")
        url = resolved

    parsed = URLParser.parse(url)
    if not parsed:
        raise ValueError("URL 解析失败")
    if parsed.get("type") != "video":
        raise ValueError(f"只支持单个视频，解析到类型: {parsed.get('type')}")

    aweme_data = await api_client.get_video_detail(parsed["aweme_id"])
    if not aweme_data:
        raise ValueError("获取作品详情失败，可能是 Cookie 失效或接口风控")

    result = _make_downloader(app)._build_no_watermark_url(aweme_data)
    if not result:
        raise ValueError("未找到可播放视频链接")

    video_url, cdn_headers = result
    title = (aweme_data.get("desc") or "video").strip() or "video"
    return video_url, cdn_headers, title


def _safe_filename(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|#\r\n]', "_", title)
    return (name[:80] or "video") + ".mp4"


# ── 路由处理 ─────────────────────────────────────────────────────────────
async def handle_health(request: web.Request) -> web.Response:
    return _json({"status": "ok"})


async def handle_options(request: web.Request) -> web.Response:
    return web.Response(status=204, headers=CORS_HEADERS)


async def handle_resolve(request: web.Request) -> web.Response:
    """GET /api/resolve?url=<文本>  →  JSON"""
    raw = request.rel_url.query.get("url", "").strip()
    if not raw:
        return _err("缺少 url 参数", 400)

    try:
        video_url, _, title = await _resolve(raw, request.app)
        return _ok({"title": title, "url": video_url})
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"内部错误: {e}", 500)


async def handle_proxy(request: web.Request) -> web.StreamResponse:
    """GET /proxy?url=<文本>  →  流式视频下载"""
    raw = request.rel_url.query.get("url", "").strip()
    if not raw:
        return _err("缺少 url 参数", 400)

    try:
        video_url, cdn_headers, title = await _resolve(raw, request.app)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"内部错误: {e}", 500)

    filename = _safe_filename(title)
    encoded_filename = quote(filename, safe="")

    async with aiohttp.ClientSession() as session:
        async with session.get(video_url, headers=cdn_headers) as cdn_resp:
            resp = web.StreamResponse(
                status=200,
                headers={
                    **CORS_HEADERS,
                    "Content-Type": "video/mp4",
                    "Content-Disposition": (
                        f"attachment; filename=\"video.mp4\";"
                        f" filename*=UTF-8''{encoded_filename}"
                    ),
                    **(
                        {"Content-Length": cdn_resp.headers["Content-Length"]}
                        if "Content-Length" in cdn_resp.headers
                        else {}
                    ),
                },
            )
            await resp.prepare(request)
            async for chunk in cdn_resp.content.iter_chunked(CHUNK_SIZE):
                await resp.write(chunk)
            await resp.write_eof()
            return resp


# ── 应用生命周期 ──────────────────────────────────────────────────────────
async def on_startup(app: web.Application) -> None:
    config = ConfigLoader("config.yml")
    cookie_manager = CookieManager()
    cookie_manager.set_cookies(config.get_cookies())

    api_client = DouyinAPIClient(
        cookie_manager.get_cookies(),
        proxy=config.get("proxy"),
    )
    await api_client.__aenter__()

    app["config"] = config
    app["cookie_manager"] = cookie_manager
    app["file_manager"] = FileManager(config.get("path") or "./Downloaded")
    app["api_client"] = api_client


async def on_cleanup(app: web.Application) -> None:
    await app["api_client"].__aexit__(None, None, None)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    app = web.Application()
    app.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/resolve", handle_resolve)
    app.router.add_get("/proxy", handle_proxy)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    print(f"服务启动于 http://0.0.0.0:{port}")
    print(f"  解析: GET http://<host>:{port}/api/resolve?url=<文本>")
    print(f"  下载: GET http://<host>:{port}/proxy?url=<文本>")
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
