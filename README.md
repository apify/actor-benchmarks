# actor-benchmarks
Repository for various Apify actor benchmarks

Repository contains small part of code reusable for different benchmarks in `src` folder. Other folders contain specific benchmarks for different actors and use cases. Each specific benchmark should contain own workflow that can be manually triggered. Such workflows can be used to run benchmarks even on unpublished changes. For example benchmarks from `crawler_actors` can be modified on branch so that all benchmarking actors are using branch specific changes from `crawlee` repository and then benchmark can be run on this branch. This allows for convenient performance evaluation of unmerged changes

## Concurrency system benchmarks

`crawler_actors/parsel_crawler_default_concurrency_py` and `crawler_actors/parsel_crawler_throughput_concurrency_py` are two copies of the Parsel crawler that differ only in the concurrency system: the first uses the default `ConcurrencySystem`, the second the `ThroughputConcurrencySystem` from [apify/crawlee-python#2328](https://github.com/apify/crawlee-python/pull/2328). Both install crawlee from that PR's branch, pinned in their `uv.lock`, and talk to the platform through `apify-client` because the Apify SDK does not support the crawlee v2 branch yet. Regenerating the lock files moves them to the latest commit of the branch.

To compare them, run the `Crawler benchmarks` workflow with `crawler_name_pattern` set to `.*concurrency.*`, for example against crawlee.dev:

```json
{
"startUrls":[{"url":"https://crawlee.dev/"}],
"exclude":["https://**/products/**"],
"maxRequestsPerCrawl": 10000,
"proxyConfiguration":{"useApifyProxy": false}
}
```

To run one of them locally, put the input into `storage/key_value_stores/default/INPUT.json` in the actor directory and run `uv run python -m parsel_crawler` there. Results land in `storage/datasets/default`.
