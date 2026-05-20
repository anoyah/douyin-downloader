#!/usr/bin/env python3
import asyncio
import sys

from config import ConfigLoader
from auth import CookieManager
from storage import FileManager
from control import RateLimiter, RetryHandler, QueueManager
from core import DouyinAPIClient, URLParser
from core.video_downloader import VideoDownloader
from utils.validators import is_short_url, normalize_short_url


async def main():
    if len(sys.argv) < 2:
        print("用法: python get_url.py <抖音作品链接>")
        return

    url = sys.argv[1]

    config = ConfigLoader("config.yml")
    cookie_manager = CookieManager()
    cookie_manager.set_cookies(config.get_cookies())

    file_manager = FileManager(config.get("path") or "./Downloaded")

    async with DouyinAPIClient(
        cookie_manager.get_cookies(),
        proxy=config.get("proxy"),
    ) as api_client:

        # 支持短链
        if is_short_url(url):
            resolved = await api_client.resolve_short_url(normalize_short_url(url))
            if not resolved:
                print("短链解析失败")
                return
            url = resolved

        parsed = URLParser.parse(url)
        if not parsed:
            print("URL 解析失败")
            return

        if parsed.get("type") != "video":
            print(f"当前示例只处理单个视频，解析到类型: {parsed.get('type')}")
            return

        aweme_id = parsed.get("aweme_id")
        aweme_data = await api_client.get_video_detail(aweme_id)

        if not aweme_data:
            print("获取作品详情失败，可能是 Cookie 失效或接口风控")
            return

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
            print("未找到可播放视频链接")
            return

        video_url, headers = result

        print(video_url)


if __name__ == "__main__":
    asyncio.run(main())