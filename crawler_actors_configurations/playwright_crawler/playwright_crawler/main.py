from apify import Actor
from crawlee.crawlers import PlaywrightCrawler
from crawlee.http_clients import HttpxHttpClient
from .routes import router


async def main() -> None:
    """The crawler entry point."""
    async with Actor:
        actor_input = await Actor.get_input() or {}

        crawler = PlaywrightCrawler(
            request_handler=router,
            headless=True,
            http_client=HttpxHttpClient(),
        )

        start_urls = [
            start_url["url"] for start_url in actor_input.get("startUrls", [])
        ]
        await crawler.run(start_urls)
