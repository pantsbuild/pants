---
title: "Using Pants in CI"
slug: "using-pants-in-ci"
excerpt: "Suggestions for how to use Pants to speed up your CI (continuous integration)."
hidden: false
createdAt: "2021-05-24T23:02:54.908Z"
updatedAt: "2022-02-08T23:50:56.628Z"
---
[block:callout]
{
  "type": "info",
  "title": "Examples",
  "body": "See the example-python repository for an [example GitHub Actions worfklow](https://github.com/pantsbuild/example-python/blob/main/.github/workflows/pants.yaml)."
}
[/block]

[block:api-header]
{
  "title": "Directories to cache"
}
[/block]
In your CI's config file, we recommend caching these directories:

* `$HOME/.cache/pants/setup`: the initial bootstrapping of Pants.
* `$HOME/.cache/pants/named_caches`: caches of tools like pip and PEX.
* `$HOME/.cache/pants/lmdb_store`: cached content for prior Pants runs, e.g. prior test results.

See [Troubleshooting](doc:troubleshooting#how-to-change-your-cache-directory) for how to change these cache locations.
[block:callout]
{
  "type": "info",
  "title": "Nuking the cache when too big",
  "body": "In CI, the cache must be uploaded and downloaded every run. This takes time, so there is a tradeoff where too large of a cache will slow down your CI.\n\nYou can use this script to nuke the cache when it gets too big:\n\n```bash\nfunction nuke_if_too_big() {\n  path=$1\n  limit_mb=$2\n  size_mb=$(du -m -d0 ${path} | cut -f 1)\n  if (( ${size_mb} > ${limit_mb} )); then\n    echo \"${path} is too large (${size_mb}mb), nuking it.\"\n    rm -rf ${path}\n  fi\n}\n\nnuke_if_too_big ~/.cache/pants/lmdb_store 2048\nnuke_if_too_big ~/.cache/pants/setup 256\nnuke_if_too_big ~/.cache/pants/named_caches 1024\n```"
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Tip: check cache performance with `[stats].log`",
  "body": "Set the option `[stats].log = true` in `pants.ci.toml` for Pants to print metrics of your cache's performance at the end of the run, including the number of cache hits and the total time saved thanks to caching, e.g.:\n\n```\n  local_cache_requests: 204\n  local_cache_requests_cached: 182\n  local_cache_requests_uncached: 22\n  local_cache_total_time_saved_ms: 307200\n```\n\nYou can also add `plugins = [\"hdrhistogram\"]` to the `[GLOBAL]` section of `pants.ci.toml` for Pants to print histograms of cache performance, e.g. the size of blobs cached."
}
[/block]

[block:callout]
{
  "type": "success",
  "title": "Remote caching",
  "body": "Rather than storing your cache with your CI provider, remote caching stores the cache in the cloud, using gRPC and the open-source Remote Execution API for low-latency and fine-grained caching. \n\nThis brings several benefits over local caching:\n\n* All machines and CI jobs share the same cache.\n* Remote caching downloads precisely what is needed by your run—when it's needed—rather than pessimistically downloading the entire cache at the start of the run.\n   * No download and upload stage for your cache. \n   * No need to \"nuke\" your cache when it gets too big.\n\nSee [Remote Caching](doc:remote-caching) for more information."
}
[/block]

[block:api-header]
{
  "title": "Recommended commands"
}
[/block]
### Approach #1: only run over changed files

Because Pants understands the dependencies of your code, you can use Pants to speed up your CI by only running tests and linters over files that actually made changes.

We recommend running these commands in CI:

```shell
❯ ./pants --version  # Bootstrap Pants.
❯ ./pants \  # Check for updates to BUILD files.
   tailor --check \
   update-build-files --check
❯ ./pants --changed-since=origin/main lint
❯ ./pants \
  --changed-since=origin/main \
  --changed-dependees=transitive \
  check test
```

Because most linters do not care about a target's dependencies, we lint all changed targets, but not any dependees of those changed targets.

Meanwhile, tests should be rerun when any changes are made to the tests _or_ to dependencies of those tests, so we use the option `--changed-dependees=transitive`. `check` should also run on any transitive changes.

See [Advanced target selection](doc:advanced-target-selection) for more information on `--changed-since` and alternative techniques to select targets to run in CI.
[block:callout]
{
  "type": "warning",
  "title": "This will not handle all cases, like hooking up a new linter",
  "body": "For example, if you add a new plugin to Flake8, Pants will still only run over changed files, meaning you may miss some new lint issues.\n\nFor absolute correctness, you may want to use Approach #2. Alternatively, add conditional logic to your CI, e.g. that any changes to `pants.toml` trigger using Approach #2."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "GitHub Actions: use `Checkout`",
  "body": "To use `--changed-since`, you may want to use the [Checkout action](https://github.com/actions/checkout).\n\nBy default, Checkout will only fetch the latest commit; you likely want to set `fetch-depth`  to fetch prior commits."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "GitLab CI: disable shallow clones or fetch main branch",
  "body": "GitLab's merge pipelines make a shallow clone by default, which only contains recent commits for the feature branch being merged. That severely limits `--changed-since`. There are two possible workarounds:\n\n 1. Clone the entire repository by going to \"CI / CD\" settings and erase the number from the\n    \"Git shallow clone\" field of the \"General pipelines\" section. Don't forget to \"Save\n    changes\". This has the advantage of cloning everything, which also is the biggest\n    long-term disadvantage.\n 2. A more targeted and hence light-weight intervention leaves the shallow clone setting\n    at its default value and instead fetches the `main` branch as well:\n\n        git branch -a \n        git remote set-branches origin main\n        git fetch --depth 1 origin main\n        git branch -a \n\n    The `git branch` commands are only included to print out all available branches before\n    and after fetching `origin/main`."
}
[/block]
### Approach #2: run over everything

Alternatively, you can simply run over all your code. Pants's caching means that you will not need to rerun on changed files.

```bash
❯ ./pants --version  # Bootstrap Pants.
❯ ./pants \  # Check for updates to BUILD files.
   tailor --check \
   update-build-files --check
❯ ./pants lint check test ::
```

However, when the cache gets too big, it should be nuked (see "Directories to cache"), so your CI may end up doing more work than Approach #1.

This approach works particularly well if you are using remote caching.
[block:api-header]
{
  "title": "Configuring Pants for CI: `pants.ci.toml` (optional)"
}
[/block]
Sometimes, you may want config specific to your CI, such as turning on test coverage reports. If you want CI-specific config, create a dedicated `pants.ci.toml` [config file](doc:options). For example:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\n# Colors often work in CI, but the shell is usually not a TTY so Pants \n# doesn't attempt to use them by default.\ncolors = true\n\n[stats]\nlog = true\n\n[test]\nuse_coverage = true\n\n[coverage-py]\nreport = [\"xml\"]\nglobal_report = true\n\n[pytest]\nargs = [\"-vv\", \"--no-header\"]",
      "language": "toml",
      "name": "pants.ci.toml"
    }
  ]
}
[/block]
Then, in your CI script or config, set the environment variable `PANTS_CONFIG_FILES=pants.ci.toml` to use this new config file, in addition to `pants.toml`.

### Tuning resource consumption (advanced)

Pants allows you to control its resource consumption. These options all have sensible defaults. In most cases, there is no need to change them. However, you may benefit from tuning these options.

Concurrency options:

* [`process_execution_local_parallelism`](doc:reference-global#section-process-execution-local-parallelism): number of concurrent processes that may be executed locally.
* [`rule_threads_core`](doc:reference-global#section-rule-threads-core): number of threads to keep active to execute `@rule` logic.
* [`rule_threads_max`](doc:reference-global#section-rule-threads-max): maximum number of threads to use to execute `@rule` logic.

Memory usage options:

* [`pantsd`](doc:reference-global#section-pantsd): enable or disable the Pants daemon, which uses an in-memory cache to speed up subsequent runs after the first run in CI.
* [`pantsd_max_memory_usage`](doc:reference-global#section-pantsd-max-memory-usage): reduce or increase the size of Pantsd's in-memory cache.

The default test runners for these CI providers have the following resources. If you are using a custom runner, e.g. enterprise, check with your CI provider.
[block:parameters]
{
  "data": {
    "h-0": "CI Provider",
    "h-1": "# CPU cores",
    "h-2": "RAM",
    "0-0": "GitHub Actions, Linux",
    "1-0": "Travis, Linux",
    "2-0": "Circle CI, Linux, free plan",
    "3-0": "GitLab, Linux shared runners",
    "0-2": "7 GB",
    "0-1": "2",
    "h-3": "Docs",
    "0-3": "https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners#supported-runners-and-hardware-resources",
    "1-1": "2",
    "1-2": "7.5 GB",
    "1-3": "https://docs.travis-ci.com/user/reference/overview/#virtualisation-environment-vs-operating-system",
    "2-1": "2",
    "2-2": "4 GB",
    "2-3": "https://circleci.com/docs/2.0/credits/#free-plan",
    "3-1": "1",
    "3-2": "3.75 GB",
    "3-3": "https://docs.gitlab.com/ee/user/gitlab_com/#linux-shared-runners"
  },
  "cols": 4,
  "rows": 4
}
[/block]

[block:api-header]
{
  "title": "Tip: store Pants logs as artifacts"
}
[/block]
We recommend that you configure your CI system to store the pants log (`.pantd.d/pants.log`) as a build artifact, so that it is available in case you need to troubleshoot CI issues.

Different CI providers and systems have different ways to configure build artifacts:

* Circle CI - [Storing artifacts](https://circleci.com/docs/2.0/artifacts/)
* Github Actions - [Storing Artifacts](https://docs.github.com/en/actions/guides/storing-workflow-data-as-artifacts) - [example in the pants repo](https://github.com/pantsbuild/pants/pull/11860) 
* Bitbucket pipelines - [Using artifacts](https://support.atlassian.com/bitbucket-cloud/docs/use-artifacts-in-steps/)
* Jenkins - [Recording artifacts](https://www.jenkins.io/doc/pipeline/tour/tests-and-artifacts/)

It's particularly useful to configure your CI to always upload the log, even if prior steps in your pipeline failed.