---
title: "Using Pants in CI"
slug: "using-pants-in-ci"
excerpt: "Suggestions for how to use Pants to speed up your CI (continuous integration)."
hidden: false
createdAt: "2021-05-24T23:02:54.908Z"
---
> 📘 Examples
> 
> See the example-python repository for an [example GitHub Actions worfklow](https://github.com/pantsbuild/example-python/blob/main/.github/workflows/pants.yaml).

Directories to cache
--------------------

> 📘 The `init-pants` GitHub Action
>
> If you're using GitHub Actions to run your CI workflows, then you can use our [standard action](https://github.com/pantsbuild/actions/tree/main/init-pants) to set up and cache the Pants bootstrap state. Otherwise, read on to learn how to configure this manually.

In your CI's config file, we recommend caching these directories:

- `$HOME/.cache/nce` (Linux) or `$HOME/Library/Caches/nce` (macOS)<br>
  This is the cache directory used by the [Pants launcher binary](doc:installation) to cache the assets, interpreters and venvs required to run Pants itself. Cache this against the Pants version, as specified in `pants.toml`. See the [pantsbuild/example-python](https://github.com/pantsbuild/example-python/blob/main/.github/workflows/pants.yaml) repo for an example of how to generate an effective cache key for this directory in GitHub Actions.
- `$HOME/.cache/pants/named_caches`<br>
  Caches used by some underlying tools.  Cache this against the inputs to those tools. For the `pants.backend.python` backend, named caches are used by PEX, and therefore its inputs are your lockfiles. Again, see [pantsbuild/example-python](https://github.com/pantsbuild/example-python/blob/main/.github/workflows/pants.yaml) for an example.

If you're not using a fine-grained [remote caching](doc:remote-caching-execution) service, then you may also want to preserve the local Pants cache at `$HOME/.cache/pants/lmdb_store`. This has to be invalidated on any file that can affect any process, e.g., `hashFiles('**/*')` on GitHub Actions.

Computing such a coarse hash, and saving and restoring large directories, can be unwieldy. So this may be impractical and slow on medium and large repos.

A [remote cache service](doc:remote-caching-execution) integrates with Pants's fine-grained invalidation and avoids these problems, and is recommended for the best CI performance.

See [Troubleshooting](doc:troubleshooting#how-to-change-your-cache-directory) for how to change these cache locations.

> 📘 Nuking the cache when too big
> 
> In CI, the cache must be uploaded and downloaded every run. This takes time, so there is a tradeoff where too large a cache will slow down your CI.
> 
> You can use this script to nuke the cache when it gets too big:
> 
> ```bash
>  function nuke_if_too_big() {
>    path=$1
>    limit_mb=$2
>    size_mb=$(du -m -d0 "${path}" | cut -f 1)
>    if (( size_mb > limit_mb )); then
>      echo "${path} is too large (${size_mb}mb), nuking it."
>      rm -rf "${path}"
>    fi
>  }
>
> nuke_if_too_big ~/.cache/nce 512
> nuke_if_too_big ~/.cache/pants/named_caches 1024
> ```

> 📘 Tip: check cache performance with `[stats].log`
> 
> Set the option `[stats].log = true` in `pants.ci.toml` for Pants to print metrics of your cache's performance at the end of the run, including the number of cache hits and the total time saved thanks to caching, e.g.:
> 
> ```
>   local_cache_requests: 204
>   local_cache_requests_cached: 182
>   local_cache_requests_uncached: 22
>   local_cache_total_time_saved_ms: 307200
> ```
> 
> You can also add `plugins = ["hdrhistogram"]` to the `[GLOBAL]` section of `pants.ci.toml` for Pants to print histograms of cache performance, e.g. the size of blobs cached.

> 👍 Remote caching
> 
> Rather than storing your cache with your CI provider, remote caching stores the cache in the cloud, using gRPC and the open-source Remote Execution API for low-latency and fine-grained caching.
> 
> This brings several benefits over local caching:
> 
> - All machines and CI jobs share the same cache.
> - Remote caching downloads precisely what is needed by your run—when it's needed—rather than pessimistically downloading the entire cache at the start of the run.
>   - No download and upload stage for your cache. 
>   - No need to "nuke" your cache when it gets too big.
> 
> See [Remote Caching and Execution](doc:remote-caching-execution) for more information.

Recommended commands
--------------------

With both approaches, you may want to shard the input targets into multiple CI jobs, for increased parallelism. See [Advanced Target Selection](doc:advanced-target-selection#sharding-the-input-targets). (This is typically less necessary when using [remote caching](doc:remote-caching-execution).)

### Approach #1: only run over changed files

Because Pants understands the dependencies of your code, you can use Pants to speed up your CI by only running tests and linters over files that actually made changes.

We recommend running these commands in CI:

```shell
❯ pants --version  # Bootstrap Pants.
❯ pants \
  --changed-since=origin/main \
  tailor --check \
  update-build-files --check \
  lint
❯ pants \
  --changed-since=origin/main \
  --changed-dependents=transitive \
  check test
```

Because most linters do not care about a target's dependencies, we lint all changed files and targets, but not any dependents of those changes.

Meanwhile, tests should be rerun when any changes are made to the tests _or_ to dependencies of those tests, so we use the option `--changed-dependents=transitive`. `check` should also run on any transitive changes.

See [Advanced target selection](doc:advanced-target-selection) for more information on `--changed-since` and alternative techniques to select targets to run in CI.

> 🚧 This will not handle all cases, like hooking up a new linter
> 
> For example, if you add a new plugin to Flake8, Pants will still only run over changed files, meaning you may miss some new lint issues.
> 
> For absolute correctness, you may want to use Approach #2. Alternatively, add conditional logic to your CI, e.g. that any changes to `pants.toml` trigger using Approach #2.

> 📘 GitHub Actions: use `Checkout`
> 
> To use `--changed-since`, you may want to use the [Checkout action](https://github.com/actions/checkout).
> 
> By default, Checkout will only fetch the latest commit; you likely want to set `fetch-depth`  to fetch prior commits.

> 📘 GitLab CI: disable shallow clones or fetch main branch
> 
> GitLab's merge pipelines make a shallow clone by default, which only contains recent commits for the feature branch being merged. That severely limits `--changed-since`. There are two possible workarounds:
> 
> 1. Clone the entire repository by going to "CI / CD" settings and erase the number from the "Git shallow clone" field of the "General pipelines" section. Don't forget to "Save changes". This has the advantage of cloning everything, which also is the biggest long-term disadvantage.
> 2. A more targeted and hence light-weight intervention leaves the shallow clone setting at its default value and instead fetches the `main` branch as well:
> 
>    ```
>    git branch -a 
>    git remote set-branches origin main
>    git fetch --depth 1 origin main
>    git branch -a 
>    ```
> 
>    The `git branch` commands are only included to print out all available branches before and after fetching `origin/main`.

### Approach #2: run over everything

Alternatively, you can simply run over all your code. Pants's caching means that you will not need to rerun on changed files.

```bash
❯ pants --version  # Bootstrap Pants.
❯ pants \
   tailor --check \
   update-build-files --check \
   lint check test ::
```

However, when the cache gets too big, it should be nuked (see "Directories to cache"), so your CI may end up doing more work than Approach #1.

This approach works particularly well if you are using [remote caching](doc:remote-caching).

Configuring Pants for CI: `pants.ci.toml` (optional)
----------------------------------------------------

Sometimes, you may want config specific to your CI, such as turning on test coverage reports. If you want CI-specific config, create a dedicated `pants.ci.toml` [config file](doc:options). For example:

```toml pants.ci.toml
[GLOBAL]
# Colors often work in CI, but the shell is usually not a TTY so Pants 
# doesn't attempt to use them by default.
colors = true

[stats]
log = true

[test]
use_coverage = true

[coverage-py]
report = ["xml"]
global_report = true

[pytest]
args = ["-vv", "--no-header"]
```

Then, in your CI script or config, set the environment variable `PANTS_CONFIG_FILES=pants.ci.toml` to use this new config file, in addition to `pants.toml`.

### Tuning resource consumption (advanced)

Pants allows you to control its resource consumption. These options all have sensible defaults. In most cases, there is no need to change them. However, you may benefit from tuning these options.

Concurrency options:

- [`process_execution_local_parallelism`](doc:reference-global#section-process-execution-local-parallelism): number of concurrent processes that may be executed locally.
- [`rule_threads_core`](doc:reference-global#section-rule-threads-core): number of threads to keep active to execute `@rule` logic.
- [`rule_threads_max`](doc:reference-global#section-rule-threads-max): maximum number of threads to use to execute `@rule` logic.

Memory usage options:

- [`pantsd`](doc:reference-global#section-pantsd): enable or disable the Pants daemon, which uses an in-memory cache to speed up subsequent runs after the first run in CI.
- [`pantsd_max_memory_usage`](doc:reference-global#section-pantsd-max-memory-usage): reduce or increase the size of Pantsd's in-memory cache.

The default test runners for these CI providers have the following resources. If you are using a custom runner, e.g. enterprise, check with your CI provider.

| CI Provider                  | Cores  | RAM     | Docs                                                                                                                                        |
| :--------------------------- | :----- | :------ | :------------------------------------------------------------------------------------------------------------------------------------------ |
| GitHub Actions, Linux        | 2      | 7 GB    | [link](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners#supported-runners-and-hardware-resources) |
| Travis, Linux                | 2      | 7.5 GB  | [link](https://docs.travis-ci.com/user/reference/overview/#virtualisation-environment-vs-operating-system)                                  |
| Circle CI, Linux, free plan  | 2      | 4 GB    | [link](https://circleci.com/docs/2.0/credits/#free-plan)                                                                                    |
| GitLab, Linux shared runners | 1      | 3.75 GB | [link](https://docs.gitlab.com/ee/user/gitlab_com/#linux-shared-runners)                                                                    |

Tip: store Pants logs as artifacts
----------------------------------

We recommend that you configure your CI system to store the pants log (`.pantsd.d/pants.log`) as a build artifact, so that it is available in case you need to troubleshoot CI issues.

Different CI providers and systems have different ways to configure build artifacts:

- Circle CI - [Storing artifacts](https://circleci.com/docs/2.0/artifacts/)
- Github Actions - [Storing Artifacts](https://docs.github.com/en/actions/guides/storing-workflow-data-as-artifacts) - [example in the pants repo](https://github.com/pantsbuild/pants/pull/11860) 
- Bitbucket pipelines - [Using artifacts](https://support.atlassian.com/bitbucket-cloud/docs/use-artifacts-in-steps/)
- Jenkins - [Recording artifacts](https://www.jenkins.io/doc/pipeline/tour/tests-and-artifacts/)

It's particularly useful to configure your CI to always upload the log, even if prior steps in your pipeline failed.
