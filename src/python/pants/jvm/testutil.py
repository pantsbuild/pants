# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import os
from dataclasses import dataclass

import pytest

from pants.core.util_rules import archive
from pants.core.util_rules.archive import UnzipBinary
from pants.engine.fs import Digest, RemovePrefix, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, rule


def maybe_skip_jdk_test(func):
    run_jdk_tests = bool(ast.literal_eval(os.environ.get("PANTS_RUN_JDK_TESTS", "True")))
    return pytest.mark.skipif(not run_jdk_tests, reason="Skip JDK tests")(func)


@dataclass(frozen=True)
class RenderedClasspath:
    """The contents of a classpath, organized as a key per entry with its contained classfiles."""

    content: dict[str, set[str]]


@rule
async def render_classpath(snapshot: Snapshot, unzip_binary: UnzipBinary) -> RenderedClasspath:
    dest_dir = "dest"
    process_results = await MultiGet(
        Get(
            ProcessResult,
            Process(
                argv=[
                    unzip_binary.path,
                    "-d",
                    dest_dir,
                    filename,
                ],
                input_digest=snapshot.digest,
                output_directories=(dest_dir,),
                description=f"Extract {filename}",
            ),
        )
        for filename in snapshot.files
    )

    listing_snapshots = await MultiGet(
        Get(Snapshot, RemovePrefix(pr.output_digest, dest_dir)) for pr in process_results
    )

    return RenderedClasspath(
        {path: set(listing.files) for path, listing in zip(snapshot.files, listing_snapshots)}
    )


def rules():
    return [
        *collect_rules(),
        *archive.rules(),
        QueryRule(RenderedClasspath, (Digest,)),
    ]
