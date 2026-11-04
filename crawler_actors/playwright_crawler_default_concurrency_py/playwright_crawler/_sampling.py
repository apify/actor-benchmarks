"""Periodic sampling of the crawler's concurrency state, for evaluating a concurrency system."""

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timezone
from time import monotonic
from typing import Any

# The repository's own environment has the released crawlee, which has neither the `crawlee.autoscaling` module nor
# the crawler's `concurrency_system` property nor the RQ's `get_pending_count()`, so the type check runs against the
# wrong version of crawlee here.
from crawlee.autoscaling import ConcurrencySystem  # ty: ignore
from crawlee.crawlers import BasicCrawler

from ._platform import PlatformIO

logger = logging.getLogger(__name__)

SAMPLES_KEY = "CONCURRENCY_SAMPLES"
"""Key of the record in the run's default key-value store that holds the samples."""


class ConcurrencySampler:
    """Records the state of the crawler's concurrency system at a fixed interval.

    Each sample holds the desired and current concurrency, the cumulative request counts, the throughput and mean
    request duration since the previous sample, and for each machine resource the share of the recent window the
    system saw it overloaded, which is what the system scales down by. The samples are written to
    the `CONCURRENCY_SAMPLES` record of the run's default key-value store after every sample, so a run that fails
    keeps the samples taken until then.
    """

    def __init__(
        self,
        crawler: BasicCrawler[Any, Any],
        platform: PlatformIO,
        interval_secs: float = 10,
    ) -> None:
        self._crawler = crawler
        self._platform = platform
        self._interval_secs = interval_secs
        self._samples: list[dict[str, Any]] = []
        self._started_at = monotonic()
        self._last_sample_at = self._started_at
        self._last_finished = 0
        self._last_finished_duration = 0.0

    async def run(
        self, crawl: Coroutine[Any, Any, Any], *, stop_after_secs: float | None = None
    ) -> None:
        """Run the crawl while sampling, and take a last sample once it finishes.

        With `stop_after_secs`, the crawler is told to stop once that many seconds have passed. The requests in
        flight still finish, and they are sampled until the crawl ends.
        """
        crawl_task = asyncio.ensure_future(crawl)
        next_sample_at = monotonic() + self._interval_secs
        stop_at = None if stop_after_secs is None else monotonic() + stop_after_secs
        try:
            while not crawl_task.done():
                wake_at = (
                    next_sample_at if stop_at is None else min(next_sample_at, stop_at)
                )
                await asyncio.wait(
                    {crawl_task}, timeout=max(0.0, wake_at - monotonic())
                )
                if stop_at is not None and monotonic() >= stop_at:
                    self._crawler.stop(
                        f"The crawl reached its time limit of {stop_after_secs} s"
                    )
                    stop_at = None
                if crawl_task.done() or monotonic() >= next_sample_at:
                    await self._sample()
                    next_sample_at = monotonic() + self._interval_secs
        except BaseException:
            crawl_task.cancel()
            raise
        await crawl_task

    async def _sample(self) -> None:
        concurrency_system = self._crawler.concurrency_system  # ty: ignore
        if concurrency_system is None:
            return

        now = monotonic()
        state = self._crawler.statistics.state
        request_manager = await self._crawler.get_request_manager()

        elapsed = now - self._last_sample_at
        finished_delta = state.requests_finished - self._last_finished
        finished_duration = state.request_total_finished_duration.total_seconds()
        duration_delta = finished_duration - self._last_finished_duration

        sample: dict[str, Any] = {
            "time": round(now - self._started_at, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "desired_concurrency": concurrency_system.desired_concurrency,
            "current_concurrency": concurrency_system.current_concurrency,
            "requests_finished": state.requests_finished,
            "requests_failed": state.requests_failed,
            "requests_retries": state.requests_retries,
            "requests_pending": await request_manager.get_pending_count(),  # ty: ignore
            "throughput": round(finished_delta / elapsed, 3) if elapsed else None,
            "avg_request_duration": (
                round(duration_delta / finished_delta, 3) if finished_delta else None
            ),
        }
        if concurrency_system.active and isinstance(
            concurrency_system, ConcurrencySystem
        ):
            status = concurrency_system.get_current_status()
            sample.update(
                {
                    "cpu_overloaded_ratio": round(status.cpu_info.actual_ratio, 3),
                    "memory_overloaded_ratio": round(
                        status.memory_info.actual_ratio, 3
                    ),
                    "event_loop_overloaded_ratio": round(
                        status.event_loop_info.actual_ratio, 3
                    ),
                    "is_system_idle": status.is_system_idle,
                }
            )

        self._samples.append(sample)
        self._last_sample_at = now
        self._last_finished = state.requests_finished
        self._last_finished_duration = finished_duration

        logger.info(
            f"Concurrency sample: desired={sample['desired_concurrency']} "
            f"current={sample['current_concurrency']} "
            f"finished={sample['requests_finished']} "
            f"pending={sample['requests_pending']} "
            f"throughput={sample['throughput']} req/s "
            f"avg_duration={sample['avg_request_duration']} s"
        )
        await self._platform.set_value(
            SAMPLES_KEY,
            {"interval_secs": self._interval_secs, "samples": self._samples},
        )
