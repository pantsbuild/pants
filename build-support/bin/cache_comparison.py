# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from time import time


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "A (remote) cache comparison tool, which automates testing a range of Pants "
            "builds (each in isolated cache namespaces) against a range of sources."
        )
    )

    parser.add_argument(
        "-a",
        "--args",
        default="check lint test ::",
        help="The arguments to test each source commit with.",
    )
    parser.add_argument(
        "-b",
        "--build-diffspec",
        help="The diffspec (e.g.: `main~10..main`) which selects the Pants builds to compare.",
    )
    parser.add_argument(
        "--build-diffspec-step",
        default=1,
        help="The number of commits to step by within `--build-diffspec`.",
    )
    parser.add_argument(
        "-s",
        "--source-diffspec",
        help=(
            "The diffspec (e.g.: `main~10..main`) which selects the Pants-repo source commits "
            "to run each Pants build against."
        ),
    )
    parser.add_argument(
        "--source-diffspec-step",
        default=1,
        help="The number of commits to step by within `--source-diffspec`.",
    )
    return parser


def main() -> None:
    args = create_parser().parse_args()
    build_commits = commits_in_range(args.build_diffspec, int(args.build_diffspec_step))
    source_commits = commits_in_range(args.source_diffspec, int(args.source_diffspec_step))
    timings = timings_by_build(
        shlex.split(args.args),
        build_commits,
        source_commits,
    )
    json.dump(timings, indent=2, fp=sys.stdout)


Commit = str


TimeInSeconds = float


def commits_in_range(diffspec: str, step: int) -> list[Commit]:
    all_commits = list(
        subprocess.run(
            ["git", "rev-list", "--reverse", diffspec],
            stdout=subprocess.PIPE,
            check=True,
        )
        .stdout.decode()
        .splitlines()
    )
    return all_commits[::step]


def timings_by_build(
    args: list[str], build_commits: list[Commit], source_commits: list[Commit]
) -> list[tuple[Commit, list[TimeInSeconds]]]:
    """For each build commit, build a PEX, and then collect timings for each source commit."""
    result = []
    for build_commit in build_commits:
        # Build a PEX for the commit, then ensure that `pantsd` is not running.
        checkout(build_commit)
        run(["package", "src/python/pants/bin:pants"], use_pex=False)
        shutil.rmtree(".pids")
        # Then collect a runtime for each commit in the range.
        cache_namespace = f"cache-comparison-{build_commit}-{time()}"
        result.append(
            (
                build_commit,
                [
                    timing_for_commit(source_commit, args, cache_namespace)
                    for source_commit in source_commits
                ],
            )
        )
    return result


def timing_for_commit(commit: Commit, args: list[str], cache_namespace: str) -> TimeInSeconds:
    checkout(commit)
    start = time()
    run(args, cache_namespace=cache_namespace)
    return time() - start


def checkout(commit: Commit) -> None:
    subprocess.run(["git", "checkout", commit], check=True)


def run(args: list[str], *, cache_namespace: str | None = None, use_pex: bool = True) -> None:
    cmd = "dist/src.python.pants.bin/pants.pex" if use_pex else "./pants"
    subprocess.run(
        [cmd, *pants_options(cache_namespace), *args],
        check=True,
    )


def pants_options(cache_namespace: str | None = None) -> list[str]:
    return [
        "--no-local-cache",
        "--pants-config-files=pants.ci.toml",
        *(
            []
            if cache_namespace is None
            else [f"--process-execution-cache-namespace={cache_namespace}"]
        ),
    ]


if __name__ == "__main__":
    main()
