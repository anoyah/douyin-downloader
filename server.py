#!/usr/bin/env python3
"""
本地 HTTP 服务。

端点：
  GET /get_url?url=<抖音链接或分享文案>   → 302 跳转到无水印直链（在线播放）
  GET /download?url=<抖音链接或分享文案>  → 代理流式下载（手机浏览器直接保存）

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


async def _resolve(
    raw: str, app: web.Application
) -> Tuple[str, Dict[str, str], str]:
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


def _error(status: int, msg: str) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"error": msg}, ensure_ascii=False),
    )


async def handle_get_url(request: web.Request) -> web.Response:
    raw = request.rel_url.query.get("url", "").strip()
    if not raw:
        return _error(400, "缺少 url 参数")
    try:
        video_url, _, _ = await _resolve(raw, request.app)
        raise web.HTTPFound(location=video_url)
    except web.HTTPException:
        raise
    except ValueError as e:
        return _error(422, str(e))
    except Exception as e:
        return _error(500, f"内部错误: {e}")


async def handle_download(request: web.Request) -> web.StreamResponse:
    raw = request.rel_url.query.get("url", "").strip()
    if not raw:
        return _error(400, "缺少 url 参数")

    try:
        video_url, cdn_headers, title = await _resolve(raw, request.app)
    except ValueError as e:
        return _error(422, str(e))
    except Exception as e:
        return _error(500, f"内部错误: {e}")

    filename = _safe_filename(title)
    encoded_filename = quote(filename, safe="")  # RFC 5987 percent-encode

    # 代理流式转发，手机浏览器会弹出"下载/保存"对话框
    async with aiohttp.ClientSession() as session:
        async with session.get(video_url, headers=cdn_headers) as cdn_resp:
            resp = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "video/mp4",
                    # filename= 给旧浏览器兜底，filename*= 给现代浏览器用中文名
                    "Content-Disposition": f"attachment; filename=\"video.mp4\"; filename*=UTF-8''{encoded_filename}",
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
    app.router.add_get("/download", handle_download)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    print(f"服务启动于 http://0.0.0.0:{port}")
    print(f"  播放: GET http://<host>:{port}/get_url?url=<抖音链接或分享文案>")
    print(f"  下载: GET http://<host>:{port}/download?url=<抖音链接或分享文案>")
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
