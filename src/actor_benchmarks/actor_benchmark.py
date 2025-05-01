import logging
import os
from dataclasses import field, dataclass, fields, asdict
from datetime import datetime, timezone
from functools import reduce
from operator import add
from typing import Self

from apify_client import ApifyClientAsync

logger = logging.getLogger("benchmark_logger")

APIFY_TOKEN_ENV_VARIABLE_NAME = "APIFY_API_TOKEN"


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

    @classmethod
    async def from_actor_run(
        cls, run_id: str, actor_lock_file: str = "", benchmark_version: str = ""
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
        )


@dataclass(kw_only=True)
class ActorBenchmark:
    meta_data: ActorBenchmarkMetadata

    @classmethod
    async def from_actor_run(
        cls, run_id: str, actor_lock_file: str = "", benchmark_version: str = "1"
    ) -> Self:
        """Generate benchmark from existing actor run.

        Args:
            run_id: actor run id used to generate benchmark.
            actor_lock_file: additional detailed information about actor version dependencies
            benchmark_version: version of the benchmark

        Returns:
            Benchmark created from actor run.
        """
        meta_data = await ActorBenchmarkMetadata.from_actor_run(
            run_id=run_id,
            actor_lock_file=actor_lock_file,
            benchmark_version=benchmark_version,
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
        benchmark_field_names = {field.name for field in fields(cls)} - {"meta_data"}
        benchmark_fields = {}
        for benchmark_field_name in benchmark_field_names:
            benchmark_fields[benchmark_field_name] = reduce(
                add,
                (
                    getattr(benchmark, benchmark_field_name)
                    for benchmark in actor_benchmarks
                ),
            ) / len(actor_benchmarks)

        return cls(meta_data=actor_benchmarks[0].meta_data, **benchmark_fields)

    async def save_to_vs(self) -> None:
        """Save benchmark to kvs named as the class name. Key of the record is the current date and time."""
        client = ApifyClientAsync(token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME))
        # Ensure kvs exists
        kvs = await client.key_value_stores().get_or_create(
            name=self.__class__.__name__
        )
        kvs_id = kvs.get("id", "")
        # Store benchmark in kvs
        record_key = self.meta_data.actor_name + datetime.now(tz=timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%S"
        )
        logger.info(
            f"Saving benchmark to key value store: {kvs_id=} under key: {record_key}.\n"
            f"Link: https://api.apify.com/v2/key-value-stores/{kvs_id}/records/{record_key}"
        )
        await client.key_value_store(kvs_id).set_record(
            key=record_key,
            value=asdict(self),
            content_type="application/json",
        )
