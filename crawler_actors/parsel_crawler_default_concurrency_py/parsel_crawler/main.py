from re import Pattern
from typing import Any

from crawlee import Glob, ConcurrencySettings
from crawlee.crawlers import ParselCrawler, ParselCrawlingContext, BasicCrawlerOptions

from ._platform import PlatformIO, create_proxy_configuration
from ._sampling import ConcurrencySampler


async def main() -> None:
    """The crawler entry point.

    Benchmark variant that uses the default `ConcurrencySystem`. Its counterpart in
    `parsel_crawler_throughput_concurrency_py` uses the `ThroughputConcurrencySystem` with otherwise identical
    settings and the same crawlee version.
    """
    platform = PlatformIO()
    actor_input = await platform.get_input()
    proxy = create_proxy_configuration(actor_input.get("proxyConfiguration"))

    crawler_kwargs: BasicCrawlerOptions[ParselCrawlingContext] = {
        "concurrency_settings": ConcurrencySettings(
            desired_concurrency=actor_input.get("desiredConcurrency", 10)
        ),
        "max_requests_per_crawl": actor_input.get("maxRequestsPerCrawl"),
    }
    if proxy:
        crawler_kwargs["proxy_configuration"] = proxy

    crawler = ParselCrawler(**crawler_kwargs)

    start_urls = [start_url["url"] for start_url in actor_input.get("startUrls", [])]
    exclude: list[Pattern[Any] | Glob] = [
        Glob(pattern) for pattern in actor_input.get("exclude", [])
    ]

    @crawler.router.default_handler
    async def default_handler(context: ParselCrawlingContext) -> None:
        """Default request handler."""
        context.log.info(f"Processing {context.request.url} ...")
        title = context.selector.xpath("//title/text()").get()
        await platform.push_data({"url": context.request.loaded_url, "title": title})
        await context.enqueue_links(exclude=exclude)

    sampler = ConcurrencySampler(crawler, platform)
    await sampler.run(crawler.run(start_urls))
