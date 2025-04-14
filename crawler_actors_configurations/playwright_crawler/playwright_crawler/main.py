from apify import Actor
from crawlee import Glob
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.http_clients import HttpxHttpClient


async def main() -> None:
    """The crawler entry point."""
    async with Actor:
        actor_input = await Actor.get_input() or {}

        crawler = PlaywrightCrawler(headless=True, http_client=HttpxHttpClient())

        start_urls = [
            start_url["url"] for start_url in actor_input.get("startUrls", [])
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

            await context.enqueue_links(exclude=[Glob(actor_input.get("exclude", ""))])

        await crawler.run(start_urls)
