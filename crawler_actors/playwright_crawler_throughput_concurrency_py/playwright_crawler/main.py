from re import Pattern
from typing import Any

from crawlee import Glob, ConcurrencySettings

# The repository's own environment has the released crawlee, which has neither the `crawlee.autoscaling` module nor
# the `concurrency_system` option, so the type check runs against the wrong version of crawlee here.
from crawlee.autoscaling import ThroughputConcurrencySystem  # ty: ignore
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.crawlers._playwright._playwright_crawler import PlaywrightCrawlerOptions

from ._platform import PlatformIO, configure_crawlee, create_proxy_configuration
from ._sampling import ConcurrencySampler


async def main() -> None:
    """The crawler entry point.

    Benchmark variant that uses the experimental `ThroughputConcurrencySystem`. Its counterpart in
    `playwright_crawler_default_concurrency_py` uses the default `ConcurrencySystem` with otherwise identical
    settings and the same crawlee version.
    """
    configure_crawlee()
    platform = PlatformIO()
    actor_input = await platform.get_input()
    proxy = create_proxy_configuration(actor_input.get("proxyConfiguration"))

    concurrency_settings = ConcurrencySettings(
        desired_concurrency=actor_input.get("desiredConcurrency", 10)
    )

    async with ThroughputConcurrencySystem(concurrency_settings) as concurrency_system:
        crawler_kwargs: PlaywrightCrawlerOptions = {
            "headless": True,
            "concurrency_system": concurrency_system,  # ty: ignore[invalid-key]
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
            await platform.push_data(
                {
                    "url": context.request.loaded_url,
                    "title": await title.inner_text() if title else None,
                }
            )

            await context.enqueue_links(exclude=exclude)

        sampler = ConcurrencySampler(crawler, platform)
        await sampler.run(crawler.run(start_urls))
