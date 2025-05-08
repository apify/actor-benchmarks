import logging
import os
import statistics
from dataclasses import field, dataclass, fields, asdict
from datetime import datetime
from numbers import Number
from typing import Self

from apify_client import ApifyClientAsync

logger = logging.getLogger("benchmark_logger")

APIFY_TOKEN_ENV_VARIABLE_NAME = "APIFY_API_TOKEN"
_STORAGE_NAME_LIMIT = 63


def set_logging_config() -> None:
    """Set logging configuration for the benchmark."""
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


@dataclass()
class ActorBenchmarkMetadata:
    actor_name: str = ""
    benchmark_version: str = ""
    actor_inputs: dict = field(default_factory=dict)
    run_options: dict = field(default_factory=dict)
    actor_lock_file: str = field(default="", repr=False)
    created: datetime = field(default_factory=datetime.now, repr=False, compare=False)
    custom_fields: dict[str, str] = field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    async def from_actor_run(
        cls,
        run_id: str,
        actor_lock_file: str = "",
        benchmark_version: str = "",
        custom_fields: dict[str, str] | None = None,
    ) -> Self:
        client = ApifyClientAsync(token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME))
        run_client = client.run(run_id=run_id)
        run = await run_client.get()
        if run is None:
            raise ValueError("Run not found.")

        if actor := await client.actor(run["actId"]).get():
            actor_name = actor["name"]
        else:
            actor_name = run["actId"]

        actor_input = await (run_client.key_value_store()).get_record("INPUT")
        if actor_input is None:
            raise ValueError("INPUT not found.")

        actor_input_value = actor_input.get("value", {})

        return cls(
            actor_name=actor_name,
            actor_inputs=actor_input_value,
            run_options=run["options"],
            actor_lock_file=actor_lock_file,
            benchmark_version=benchmark_version,
            custom_fields=custom_fields or {},
        )


@dataclass(kw_only=True)
class ActorBenchmark:
    meta_data: ActorBenchmarkMetadata

    @classmethod
    async def from_actor_run(
        cls,
        run_id: str,
        *,
        actor_lock_file: str = "",
        benchmark_version: str = "1",
        custom_fields: dict[str, str] | None = None,
    ) -> Self:
        """Generate benchmark from existing actor run.

        Args:
            run_id: Actor run id used to generate benchmark.
            actor_lock_file: Additional detailed information about actor version dependencies.
            benchmark_version: Version of the benchmark.
            custom_fields: Custom data that can be appended to the benchmark, for example,
             specific logs or specific crawler configurations.

        Returns:
            Benchmark created from actor run.
        """
        meta_data = await ActorBenchmarkMetadata.from_actor_run(
            run_id=run_id,
            actor_lock_file=actor_lock_file,
            benchmark_version=benchmark_version,
            custom_fields=custom_fields,
        )
        return cls(meta_data=meta_data)

    @classmethod
    def aggregate_results(cls, actor_benchmarks: list[Self]) -> Self:
        """Aggregate multiple benchmarks into one.

        Args:
            actor_benchmarks: List of benchmarks to be aggregated.

        Returns:
            Aggregated benchmark.
        """
        if not actor_benchmarks:
            raise ValueError("No actor benchmarks passed.")

        for benchmark in actor_benchmarks[1:]:
            if benchmark.meta_data != actor_benchmarks[0].meta_data:
                raise ValueError("Incompatible benchmarks.")

        # Aggregate results
        metric_fields = {}

        for metric_name in actor_benchmarks[0].get_metrics().keys():
            metric_fields[metric_name] = statistics.mean(
                (getattr(benchmark, metric_name) for benchmark in actor_benchmarks)
            )

        return cls(meta_data=actor_benchmarks[0].meta_data, **metric_fields)

    def get_metrics(self) -> dict[str, Number]:
        """Return all the benchmark metrics without metadata"""
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "meta_data"
        }

    def _get_kvs_key(self, tag: str = "") -> str:
        url_datetime_format = "%Y-%m-%dT-%H-%M-%S"
        return "-".join(
            part
            for part in (
                self.meta_data.actor_name,
                tag,
                self.meta_data.created.strftime(url_datetime_format),
            )
            if part
        )

    async def save_to_kvs(self, tag: str = "") -> str:
        """Save benchmark to kvs named as the class name. Key of the record is the `{actor}-{tag}-{datetime}`."""

        # Ensure kvs exists
        client = ApifyClientAsync(token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME))
        kvs = await client.key_value_stores().get_or_create(
            name=self.__class__.__name__[-_STORAGE_NAME_LIMIT:]
        )
        kvs_id = kvs.get("id", "")

        # Store benchmark in kvs
        key = self._get_kvs_key(tag=tag)
        link = f"https://api.apify.com/v2/key-value-stores/{kvs_id}/records/{key}"
        logger.info(
            f"Saving benchmark to key value store: {kvs_id=} under key: {key}.\n"
            f"Link: {link}"
        )
        await client.key_value_store(kvs_id).set_record(
            key=key,
            value=asdict(self),
            content_type="application/json",
        )
        return link

    async def save_metrics_to_dataset(
        self, tag: str = "", kvs_details_link: str = ""
    ) -> str:
        """Save only metrics dataset. The name of the dataset is `{benchmark}-{actor}-{tag}`."""
        client = ApifyClientAsync(token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME))
        redash_datetime_format = "%Y-%m-%dT %H:%M:%S"
        # Ensure dataset exists
        dataset_name = "-".join(
            part
            for part in (
                self.__class__.__name__,
                self.meta_data.actor_name,
                tag,
            )
            if part
        )[-_STORAGE_NAME_LIMIT:]

        dataset = await client.datasets().get_or_create(name=dataset_name)
        dataset_id = dataset.get("id", "")

        link = f"https://api.apify.com/v2/datasets/{dataset_id}/items?clean=true&format=json"
        logger.info(
            f"Adding benchmark metrics to dataset: {dataset_id=}.\nLink: {link}"
        )

        metrics: dict[str, Number | str] = {**self.get_metrics()}
        metrics["datetime"] = self.meta_data.created.strftime(redash_datetime_format)
        metrics["details"] = kvs_details_link
        await client.dataset(dataset_id).push_items(metrics)
        return link
