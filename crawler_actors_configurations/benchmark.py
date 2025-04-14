import dataclasses
import json
import logging
import os
import subprocess
from datetime import timedelta
import pathlib
from functools import reduce
from operator import add
from typing import Self

from apify_client import ApifyClientAsync


TEST_USER_NAME = "apify-test"

logger = logging.getLogger("crawler_benchmark")


@dataclasses.dataclass()
class ActorBenchmarkMetadata:
    actor_name: str = ""
    benchmark_version: str = ""
    actor_inputs: dict = dataclasses.field(default_factory=dict)
    run_options: dict = dataclasses.field(default_factory=dict)
    actor_lock_file: str = ""

    @classmethod
    async def from_actor_run(
        cls, run_id: str, actor_lock_file: str = "", benchmark_version: str = ""
    ) -> Self:
        client = ApifyClientAsync(token=os.getenv("APIFY_TEST_USER_API_TOKEN"))
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


@dataclasses.dataclass(kw_only=True)
class ActorBenchmark:
    meta_data: ActorBenchmarkMetadata

    @classmethod
    def aggregate_results(cls, actor_benchmarks: list[Self]) -> Self:
        if not actor_benchmarks:
            raise ValueError("No actor benchmarks passed.")

        for benchmark in actor_benchmarks[1:]:
            if benchmark.meta_data != actor_benchmarks[0].meta_data:
                raise ValueError("Incompatible benchmarks.")

        # Aggregate results
        benchmark_field_names = {field.name for field in dataclasses.fields(cls)} - {
            "meta_data"
        }
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


@dataclasses.dataclass(kw_only=True)
class CrawlerPerformanceBenchmark(ActorBenchmark):
    valid_result_count: int = 0
    runtime: timedelta = timedelta(seconds=0)

    @classmethod
    async def from_actor_run(
        cls, run_id: str, actor_lock_file: str = "", benchmark_version: str = "1"
    ) -> Self:
        meta_data = await ActorBenchmarkMetadata.from_actor_run(
            run_id=run_id,
            actor_lock_file=actor_lock_file,
            benchmark_version=benchmark_version,
        )
        run_client = ApifyClientAsync(token=os.getenv("APIFY_TEST_USER_API_TOKEN")).run(
            run_id=run_id
        )
        run_data = await run_client.get()
        if run_data is None:
            raise ValueError("Missing run data.")
        runtime = run_data["stats"]["runTimeSecs"]

        default_dataset_client = run_client.dataset()
        results = {
            (item["title"], item["url"])
            async for item in default_dataset_client.iterate_items()
        }
        return cls(
            meta_data=meta_data,
            valid_result_count=len(results),
            runtime=timedelta(seconds=runtime),
        )

    def __str__(self) -> str:
        return (
            f"Actor: {self.meta_data.actor_name}, "
            f"Valid results: {self.valid_result_count}, "
            f"Runtime: {self.runtime.total_seconds()}s, "
        )


async def get_valid_run_ids(
    actor_name: str, run_samples: int, run_input: dict, memory_mbytes: int
) -> list[str]:
    client = ApifyClientAsync(token=os.getenv("APIFY_TEST_USER_API_TOKEN"))
    actor_client = client.actor(actor_name)

    valid_run_ids = list[str]()
    run_count = 0
    while len(valid_run_ids) < run_samples:
        # Run in sequence to not stress the test site
        run_count += 1
        logger.info(f"Starting actor: {actor_name}. Run: {run_count}")
        started_run_data = await actor_client.start(
            run_input=run_input, memory_mbytes=memory_mbytes
        )
        actor_run = client.run(started_run_data["id"])
        finished_run_data = await actor_run.wait_for_finish()

        if finished_run_data is None:
            raise RuntimeError("Missing run data")

        # Check migrationCount once available. finished_run_data["stats"]["migrationCount"]>0
        # if finished_run_data["stats"]["migrationCount"]>0 or finished_run_data['status'] != 'SUCCEEDED':
        if finished_run_data["status"] != "SUCCEEDED":
            # Actor failed or migration occurred during run. Run is not suitable for a benchmark.
            logger.info("Actor run not suitable for benchmark.")
            logger.info(
                f"Actor run status: {finished_run_data['status']}, migration count: {0}"
            )
            continue

        logger.info("Actor run successfully finished.")
        valid_run_ids.append(finished_run_data["id"])

    return valid_run_ids


async def benchmark_runs(
    run_ids: list[str], lock_file: str = ""
) -> CrawlerPerformanceBenchmark:
    benchmarks = []
    for run_id in run_ids:
        benchmark = await CrawlerPerformanceBenchmark.from_actor_run(
            run_id=run_id, actor_lock_file=lock_file
        )
        logger.info(f"Benchmark of run {run_id}, {benchmark=!s}")
        benchmarks.append(benchmark)

    aggregated_benchmark = CrawlerPerformanceBenchmark.aggregate_results(benchmarks)
    logger.info(
        f"Overall benchmark of all runs, :{aggregated_benchmark=}. \n {aggregated_benchmark.meta_data=}"
    )
    return aggregated_benchmark


async def main() -> None:
    run_samples = 2
    # Set up logging to be visible in github action
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Just for local testing
    os.environ["PATH"] = (
        f"/home/pijukatel/.nvm/versions/node/v22.11.0/bin/:{os.environ['PATH']}"
    )

    subprocess.run(  # noqa: ASYNC221, S603
        ["apify", "login", "-t", os.environ["APIFY_TEST_USER_API_TOKEN"]],  # noqa: S607
        capture_output=True,
        check=True,
    )

    current_dir = pathlib.Path(__file__).parent
    crawler_dirs = [d for d in current_dir.iterdir() if d.is_dir()]
    for actor_dir in crawler_dirs:
        with open(actor_dir / ".actor" / "actor.json") as f:
            actor_name = f"{TEST_USER_NAME}~{json.load(f)['name']}"
            logger.info(f"{actor_name=}")
        with open(actor_dir / "uv.lock", "r") as f:
            lock_file = f.read()

        logger.info(f"Building actor: {actor_name}")
        subprocess.run(
            ["apify", "push", "--force", "--no-prompt"],
            capture_output=True,
            check=True,
            cwd=actor_dir,
        )

        client = ApifyClientAsync(token=os.getenv("APIFY_TEST_USER_API_TOKEN"))

        # Run actors n times
        # Run in sequence to not stress the test site
        try:
            valid_runs = await get_valid_run_ids(
                actor_name=actor_name,
                run_samples=run_samples,
                run_input={
                    "startUrls": [
                        {
                            "url": "https://warehouse-theme-metal.myshopify.com/",
                            "method": "GET",
                        }
                    ],
                    "exclude": "https://**/products/**",
                },
                memory_mbytes=8192,
            )
            await benchmark_runs(valid_runs, lock_file=lock_file)

        finally:
            # Delete the actor once it is no longer needed.
            await client.actor(actor_name).delete()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
