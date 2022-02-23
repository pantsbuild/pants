# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import random

from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    FileContent,
    PathGlobs,
    Snapshot,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.contextutil import timed


def benchmark_subset_performance() -> None:
    rule_runner = RuleRunner(
        rules=[
            QueryRule(Digest, [CreateDigest]),
            QueryRule(DigestContents, [PathGlobs]),
            QueryRule(DigestEntries, [Digest]),
            QueryRule(DigestEntries, [PathGlobs]),
            QueryRule(Snapshot, [CreateDigest]),
            QueryRule(Snapshot, [DigestSubset]),
            QueryRule(Snapshot, [PathGlobs]),
        ],
        isolated_local_store=True,
    )

    random.seed(0)  # Ensure the same generated content every time.

    def generate_dirpath():
        num_path_segments = random.randrange(2, 6)
        path_segments = tuple(
            random.choices(["aaaaa", "bbbbb", "ccccc", "ddddd"], k=num_path_segments)
        )
        return os.path.join(*path_segments)

    # sizes = [10000, 20000, 40000, 80000, 160000, 320000]
    sizes = list(range(20000, 200000, 20000))
    digest_times = []
    subset_times = []

    for num_files in sizes:
        with timed() as timer:
            files = [
                FileContent(os.path.join(generate_dirpath(), f"{i}.txt"), b"")
                for i in range(0, num_files)
            ]
            all_paths = sorted(f.path for f in files)
        print(f"Generated {num_files} files in {timer.millis} ms")

        with timed() as timer:
            digest = rule_runner.request(
                Digest,
                [CreateDigest(files)],
            )
        digest_times.append(timer.millis)
        print(f"Created digest for {num_files} files in {timer.millis} ms")

        # Get the subset containing all paths, which should be identical to the original digest.
        with timed() as timer:
            rule_runner.request(Snapshot, [DigestSubset(digest, PathGlobs(all_paths))])
        subset_times.append(timer.millis)
        print(f"Subsetted {num_files} in {timer.millis} ms")
        print("")

    print("")
    print("size,digest_time,subset_time")
    for tup in zip(sizes, digest_times, subset_times):
        print(",".join([str(x) for x in tup]))


if __name__ == "__main__":
    benchmark_subset_performance()
