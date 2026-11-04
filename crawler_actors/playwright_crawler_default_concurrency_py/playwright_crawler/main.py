from re import Pattern
from typing import Any

from crawlee import Glob, ConcurrencySettings
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.crawlers._playwright._playwright_crawler import PlaywrightCrawlerOptions

from ._platform import PlatformIO, configure_crawlee, create_proxy_configuration
from ._sampling import ConcurrencySampler


async def main() -> None:
    """The crawler entry point.

    Benchmark variant that uses the default `ConcurrencySystem`. Its counterpart in
    `playwright_crawler_throughput_concurrency_py` uses the `ThroughputConcurrencySystem` with otherwise identical
    settings and the same crawlee version.
    """
    configure_crawlee()
    platform = PlatformIO()
    actor_input = await platform.get_input()
    proxy = create_proxy_configuration(actor_input.get("proxyConfiguration"))

    crawler_kwargs: PlaywrightCrawlerOptions = {
        "headless": True,
        "concurrency_settings": ConcurrencySettings(
            desired_concurrency=actor_input.get("desiredConcurrency", 10)
        ),
        "max_requests_per_crawl": actor_input.get("maxRequestsPerCrawl"),
    }
    if proxy:
        crawler_kwargs["proxy_configuration"] = proxy

    crawler = PlaywrightCrawler(**crawler_kwargs)

    start_urls = [start_url["url"] for start_url in actor_input.get("startUrls", [])]
    exclude: list[Pattern[Any] | Glob] = [
        Glob(pattern) for pattern in actor_input.get("exclude", [])
    ]
    include: list[Pattern[Any] | Glob] = [
        Glob(pattern) for pattern in actor_input.get("include", [])
    ]

    @crawler.router.default_handler
    async def default_handler(context: PlaywrightCrawlingContext) -> None:
        """Default request handler."""
        context.log.info(f"Processing {context.request.url} ...")
        title = await context.page.query_selector("title")
        await platform.push_data(
            {
                "url": context.request.loaded_url,
                "title": await title.inner_text() if title else None,
            }
        )

        # An empty `include` would enqueue nothing, so links are filtered by it only when the input sets it.
        if include:
            await context.enqueue_links(include=include, exclude=exclude)
        else:
            await context.enqueue_links(exclude=exclude)

    sampler = ConcurrencySampler(crawler, platform)
    await sampler.run(
        crawler.run(start_urls), stop_after_secs=actor_input.get("maxCrawlDurationSecs")
    )
