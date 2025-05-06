import dataclasses
import json
import os
import re
import typer
import asyncio
import subprocess
from datetime import timedelta
import pathlib
from typing import Self, override

from apify_client import ApifyClientAsync

from actor_benchmarks.actor_benchmark import (
    ActorBenchmark,
    ActorBenchmarkMetadata,
    logger,
    set_logging_config,
    APIFY_TOKEN_ENV_VARIABLE_NAME,
)


@dataclasses.dataclass(kw_only=True)
class CrawlerPerformanceBenchmark(ActorBenchmark):
    """Simple performance benchmark for measuring duration of run and number of valid results."""

    valid_result_count: int = 0
    runtime: timedelta = timedelta(seconds=0)

    @classmethod
    @override
    async def from_actor_run(
        cls,
        run_id: str,
        actor_lock_file: str = "",
        benchmark_version: str = "1",
        custom_fields: dict[str, str] | None = None,
    ) -> Self:
        meta_data = await ActorBenchmarkMetadata.from_actor_run(
            run_id=run_id,
            actor_lock_file=actor_lock_file,
            benchmark_version=benchmark_version,
            custom_fields=custom_fields,
        )
        run_client = ApifyClientAsync(
            token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME)
        ).run(run_id=run_id)
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


async def _get_valid_run_ids(
    actor_name: str,
    run_samples: int,
    memory_mbytes: int,
    run_input: dict | None = None,
) -> list[str]:
    """Get run ids of actor runs by running the actor several times and keeping only the valid runs."""
    client = ApifyClientAsync(token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME))
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


async def _benchmark_runs(
    run_ids: list[str], lock_file: str = ""
) -> CrawlerPerformanceBenchmark:
    """Benchmark existing actor runs."""
    benchmarks = []
    for run_id in run_ids:
        benchmark = await CrawlerPerformanceBenchmark.from_actor_run(
            run_id=run_id, actor_lock_file=lock_file
        )
        logger.info(f"Benchmark of run {run_id}, {benchmark=!s}")
        benchmarks.append(benchmark)

    aggregated_benchmark = CrawlerPerformanceBenchmark.aggregate_results(benchmarks)
    logger.info(
        f"Overall benchmark of all runs, :{aggregated_benchmark=!s}. \n {aggregated_benchmark.meta_data=}"
    )
    return aggregated_benchmark


async def benchmark_actors(
    actor_name_pattern: str, actor_input_json: str | None = None
) -> None:
    set_logging_config()

    run_samples = 10

    subprocess.run(
        ["apify", "login", "-t", os.environ[APIFY_TOKEN_ENV_VARIABLE_NAME]],
        capture_output=True,
        check=True,
    )

    client = ApifyClientAsync(token=os.getenv(APIFY_TOKEN_ENV_VARIABLE_NAME))

    user = await client.user().get()

    if user is not None:
        user_name = user["username"]
    else:
        raise RuntimeError("Missing user data")

    # Run and benchmark all crawler actors found in the directory containing this file.
    crawler_dirs = [d for d in pathlib.Path(__file__).parent.iterdir() if d.is_dir()]
    for actor_dir in crawler_dirs:
        if not re.findall(actor_name_pattern, str(actor_dir)):
            continue
        with open(actor_dir / ".actor" / "actor.json") as f:
            actor_name = f"{user_name}~{json.load(f)['name']}"
            logger.info(f"{actor_name=}")

        logger.info(f"Building actor: {actor_name}")
        subprocess.run(
            ["apify", "push", "--force", "--no-prompt"],
            capture_output=True,
            check=True,
            cwd=actor_dir,
        )

        # Run actors n times. Run in sequence to not stress the test site.
        try:
            valid_runs = await _get_valid_run_ids(
                actor_name=actor_name,
                run_samples=run_samples,
                memory_mbytes=8192,
                run_input=json.loads(actor_input_json) if actor_input_json else None,
            )

            benchmark = await _benchmark_runs(
                valid_runs, lock_file=_read_version_file(actor_dir)
            )
            await benchmark.save_to_kvs()

        finally:
            # Delete the actor once it is no longer necessary.
            await client.actor(actor_name).delete()


def _read_version_file(directory: pathlib.Path) -> str:
    version_files = ["uv.lock", "poetry.lock", "package-lock.json"]
    for version_file in version_files:
        if (path := directory / version_file).exists():
            with open(path) as f:
                return f.read()
    return ""


benchmark_cli = typer.Typer()


@benchmark_cli.command()
def run(
    actor_name_pattern: str = typer.Argument(default=r".*py"),
    actor_input_json: str | None = typer.Argument(default=None),
) -> None:
    asyncio.run(
        benchmark_actors(
            actor_name_pattern=actor_name_pattern, actor_input_json=actor_input_json
        )
    )


if __name__ == "__main__":
    benchmark_cli()
