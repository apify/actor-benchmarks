from re import Pattern
from typing import Any

from apify import Actor, ProxyConfiguration
from crawlee import Glob, ConcurrencySettings
from crawlee.crawlers import ParselCrawler, ParselCrawlingContext


async def main() -> None:
    """The crawler entry point."""
    async with Actor:
        actor_input = await Actor.get_input() or {}

        crawler = ParselCrawler(
            proxy_configuration=await Actor.create_proxy_configuration(
                actor_proxy_input=actor_input.get("proxyConfiguration")
            )
            or ProxyConfiguration(),
            concurrency_settings=ConcurrencySettings(desired_concurrency=10),
        )

        start_urls = [
            start_url["url"] for start_url in actor_input.get("startUrls", [])
        ]
        exclude: list[Pattern[Any] | Glob] = [
            Glob(pattern) for pattern in actor_input.get("exclude", [])
        ]

        @crawler.router.default_handler
        async def default_handler(context: ParselCrawlingContext) -> None:
            """Default request handler."""
            context.log.info(f"Processing {context.request.url} ...")
            title = context.selector.xpath("//title/text()").get()
            await context.push_data({"url": context.request.loaded_url, "title": title})
            await context.enqueue_links(exclude=exclude)

        await crawler.run(start_urls)
