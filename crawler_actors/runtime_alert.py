"""Send Slack warning if the latest benchmark runtime deviates from the mean of previous runtimes."""

import json
import os
import re
import statistics
import urllib.request
from datetime import datetime

from apify_client import ApifyClient

DATASET_NAME_PATTERN = os.getenv("DATASET_NAME_PATTERN", "daily-master")
HISTORY_SIZE = 10
THRESHOLD = 0.15
DATETIME_FORMAT = "%Y-%m-%dT %H:%M:%S"


def main() -> None:
    client = ApifyClient(token=os.environ["APIFY_API_TOKEN"])
    # Ignore benchmarks that were not created by the latest scheduled run.
    not_before = datetime.fromisoformat(os.environ["NOT_BEFORE"]).replace(tzinfo=None)

    warnings = []
    for dataset in client.datasets().list(unnamed=False).items:
        if not dataset.name or not re.search(DATASET_NAME_PATTERN, dataset.name):
            continue
        nice_name = (
            dataset.name[dataset.name.find("Benchmark-") :]
            if "Benchmark-" in dataset.name
            else dataset.name
        )
        print(f"Checking: {nice_name}")

        items = (
            client.dataset(dataset.id)
            .list_items(desc=True, limit=HISTORY_SIZE + 1, clean=True)
            .items
        )
        if len(items) < HISTORY_SIZE + 1:
            # Ignore benchmarks without enough samples
            continue

        latest, *previous = items
        if datetime.strptime(latest["datetime"], DATETIME_FORMAT) < not_before:
            # Already reported by alerts earlier
            continue

        mean = statistics.mean(item["runtime"] for item in previous)
        print(
            f"Mean of {HISTORY_SIZE} last measurements: {mean:.4f}\n"
            f"New sample:                   {latest['runtime']:.4f}"
        )
        difference = (latest["runtime"] - mean) / mean
        if abs(difference) > THRESHOLD:
            warnings.append(
                f"<{latest['details']}|`{nice_name}`>: runtime {latest['runtime']:.1f} s is {difference:+.0%} "
                f"vs mean {mean:.1f} s of last {len(previous)} runs. "
            )

    if not warnings:
        print("No runtime deviations found.")
        return

    message = ":warning: Benchmark runtime deviations:\n" + "\n".join(warnings)
    request = urllib.request.Request(
        os.environ["SLACK_WEBHOOK_URL"],
        data=json.dumps({"text": message}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=30).close()
    print("Deviations reported to Slack.")


if __name__ == "__main__":
    main()
