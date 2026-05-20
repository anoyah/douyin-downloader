#!/usr/bin/env python3
"""
本地 HTTP 服务，GET /get_url?url=<抖音链接> 返回无水印直链。

启动：python server.py [port]   （默认 8080）
"""
import asyncio
import json
import sys

from aiohttp import web

from config import ConfigLoader
from auth import CookieManager
from storage import FileManager
from control import RateLimiter, RetryHandler, QueueManager
from core import DouyinAPIClient, URLParser
from core.video_downloader import VideoDownloader
from utils.validators import is_short_url, normalize_short_url


async def resolve_video_url(url: str, app: web.Application) -> str:
    api_client: DouyinAPIClient = app["api_client"]
    config: ConfigLoader = app["config"]
    file_manager: FileManager = app["file_manager"]
    cookie_manager: CookieManager = app["cookie_manager"]

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

    downloader = VideoDownloader(
        config=config,
        api_client=api_client,
        file_manager=file_manager,
        cookie_manager=cookie_manager,
        database=None,
        rate_limiter=RateLimiter(),
        retry_handler=RetryHandler(),
        queue_manager=QueueManager(max_workers=1),
    )

    result = downloader._build_no_watermark_url(aweme_data)
    if not result:
        raise ValueError("未找到可播放视频链接")

    video_url, _ = result
    return video_url


async def handle_get_url(request: web.Request) -> web.Response:
    url = request.rel_url.query.get("url", "").strip()
    if not url:
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps({"error": "缺少 url 参数"}, ensure_ascii=False),
        )

    try:
        video_url = await resolve_video_url(url, request.app)
        raise web.HTTPFound(location=video_url)
    except web.HTTPException:
        raise
    except ValueError as e:
        return web.Response(
            status=422,
            content_type="application/json",
            text=json.dumps({"error": str(e)}, ensure_ascii=False),
        )
    except Exception as e:
        return web.Response(
            status=500,
            content_type="application/json",
            text=json.dumps({"error": f"内部错误: {e}"}, ensure_ascii=False),
        )


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
    app.router.add_get("/get_url", handle_get_url)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    print(f"服务启动于 http://0.0.0.0:{port}")
    print(f"用法: GET http://<host>:{port}/get_url?url=<抖音链接>")
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
