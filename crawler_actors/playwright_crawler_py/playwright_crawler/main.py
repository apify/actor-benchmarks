from re import Pattern
from typing import Any

from apify import Actor
from crawlee import Glob
from crawlee.crawlers import (
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
)
from crawlee.crawlers._playwright._playwright_crawler import PlaywrightCrawlerOptions


async def main() -> None:
    """The crawler entry point."""
    async with Actor:
        actor_input = await Actor.get_input() or {}
        proxy = await Actor.create_proxy_configuration(
            actor_proxy_input=actor_input.get("proxyConfiguration"),
        )
        crawler_kwargs: PlaywrightCrawlerOptions = {
            "headless": True,
            "max_requests_per_crawl": actor_input.get("maxRequestsPerCrawl"),
        }
        if proxy:
            crawler_kwargs["proxy_configuration"] = proxy

        crawler = PlaywrightCrawler(**crawler_kwargs)

        start_urls = [
            start_url["url"] for start_url in actor_input.get("startUrls", [])
        ]
        exclude: list[Pattern[Any] | Glob] = [
            Glob(pattern) for pattern in actor_input.get("exclude", [])
        ]

        @crawler.router.default_handler
        async def default_handler(context: PlaywrightCrawlingContext) -> None:
            """Default request handler."""
            context.log.info(f"Processing {context.request.url} ...")
            title = await context.page.query_selector("title")
            await context.push_data(
                {
                    "url": context.request.loaded_url,
                    "title": await title.inner_text() if title else None,
                }
            )

            await context.enqueue_links(exclude=exclude)

        await crawler.run(start_urls)
