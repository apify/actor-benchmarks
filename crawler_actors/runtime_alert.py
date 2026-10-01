"""Send Slack warning if the latest benchmark runtime deviates from the average of previous runtimes."""

import json
import os
import re
import statistics
import urllib.request
from datetime import datetime

from apify_client import ApifyClient

DATASET_NAME_PATTERN = os.getenv("DATASET_NAME_PATTERN", "daily-master")
HISTORY_SIZE = 10
THRESHOLD = 0.3
DATETIME_FORMAT = "%Y-%m-%dT %H:%M:%S"


def main() -> None:
    client = ApifyClient(token=os.environ["APIFY_API_TOKEN"])
    # Ignore benchmarks that were not created by the latest scheduled run.
    not_before = datetime.fromisoformat(os.environ["NOT_BEFORE"]).replace(tzinfo=None)

    warnings = []
    for dataset in client.datasets().list(unnamed=False).items:
        if not dataset.name or not re.search(DATASET_NAME_PATTERN, dataset.name):
            continue

        items = (
            client.dataset(dataset.id)
            .list_items(desc=True, limit=HISTORY_SIZE + 1, clean=True)
            .items
        )
        if len(items) < 2:
            continue

        latest, *previous = items
        if datetime.strptime(latest["datetime"], DATETIME_FORMAT) < not_before:
            continue

        average = statistics.mean(item["runtime"] for item in previous)
        difference = (latest["runtime"] - average) / average
        if abs(difference) > THRESHOLD:
            warnings.append(
                f"`{dataset.name}`: runtime {latest['runtime']:.1f} s is {difference:+.0%} "
                f"vs average {average:.1f} s of last {len(previous)} runs. {latest['details']}"
            )

    if not warnings:
        print("No runtime deviations found.")
        return

    message = ":warning: Benchmark runtime deviations:\n" + "\n".join(warnings)
    print(message)
    request = urllib.request.Request(
        os.environ["SLACK_WEBHOOK_URL"],
        data=json.dumps({"text": message}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=30).close()


if __name__ == "__main__":
    main()
