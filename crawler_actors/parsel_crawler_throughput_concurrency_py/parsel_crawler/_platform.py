"""Platform integration for the benchmark crawler.

The Apify SDK does not support the crawlee v2 branch yet, so the crawler reads its input and writes its results through
`apify-client` directly. Outside the platform, it falls back to crawlee's local storage.
"""

import json
import logging
import os
import pathlib
from typing import Any

from apify_client import ApifyClientAsync
from crawlee import service_locator
from crawlee.configuration import Configuration
from crawlee.proxy_configuration import ProxyConfiguration
from crawlee.storages import Dataset, KeyValueStore

logger = logging.getLogger(__name__)

_LOCAL_INPUT_FILE = pathlib.Path("storage/key_value_stores/default/INPUT.json")
"""Input of a local run. Crawlee purges the default key-value store on start, so the file is read from disk."""


def is_at_home() -> bool:
    """Whether the crawler runs as an Actor on the Apify platform."""
    return os.environ.get("APIFY_IS_AT_HOME") == "1"


def configure_crawlee() -> None:
    """Apply the crawlee configuration the Apify SDK applies on the platform. Call it before creating a crawler.

    The platform's containers run as root, where Chromium refuses to start with its sandbox on, so the SDK disables
    the browser sandbox there. Crawlee's own configuration only reads the flag from an environment variable the
    platform does not set.
    """
    if is_at_home():
        service_locator.set_configuration(Configuration(disable_browser_sandbox=True))


class PlatformIO:
    """Reads the Actor input and writes to the run's default dataset and key-value store."""

    def __init__(self) -> None:
        self._client: ApifyClientAsync | None = None
        if is_at_home():
            self._client = ApifyClientAsync(token=os.environ["APIFY_TOKEN"])
        else:
            logger.info(
                "Not running on the Apify platform, using local crawlee storage."
            )

    async def get_input(self) -> dict[str, Any]:
        if self._client is None:
            if not _LOCAL_INPUT_FILE.exists():
                return {}
            return json.loads(_LOCAL_INPUT_FILE.read_text()) or {}

        kvs_client = self._client.key_value_store(
            os.environ["ACTOR_DEFAULT_KEY_VALUE_STORE_ID"]
        )
        record = await kvs_client.get_record(os.environ["ACTOR_INPUT_KEY"])
        if record is None:
            return {}
        return record["value"] or {}

    async def push_data(self, item: dict[str, Any]) -> None:
        if self._client is None:
            dataset = await Dataset.open()
            await dataset.push_data(item)
            return

        dataset_client = self._client.dataset(os.environ["ACTOR_DEFAULT_DATASET_ID"])
        await dataset_client.push_items(item)

    async def set_value(self, key: str, value: Any) -> None:
        """Store a JSON value under `key` in the run's default key-value store."""
        if self._client is None:
            kvs = await KeyValueStore.open()
            await kvs.set_value(key, value)
            return

        kvs_client = self._client.key_value_store(
            os.environ["ACTOR_DEFAULT_KEY_VALUE_STORE_ID"]
        )
        await kvs_client.set_record(key, value, content_type="application/json")


def create_proxy_configuration(
    proxy_input: dict[str, Any] | None,
) -> ProxyConfiguration | None:
    """Build an Apify Proxy configuration from the `proxyConfiguration` Actor input, if it asks for one."""
    if not proxy_input or not proxy_input.get("useApifyProxy"):
        return None

    groups = proxy_input.get("apifyProxyGroups") or []
    username = f"groups-{'+'.join(groups)}" if groups else "auto"
    password = os.environ["APIFY_PROXY_PASSWORD"]
    hostname = os.environ.get("APIFY_PROXY_HOSTNAME", "proxy.apify.com")
    port = os.environ.get("APIFY_PROXY_PORT", "8000")
    return ProxyConfiguration(
        proxy_urls=[f"http://{username}:{password}@{hostname}:{port}"]
    )
