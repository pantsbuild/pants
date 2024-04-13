# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import dataclasses
import os
from dataclasses import dataclass

import pytest

from pants.build_graph.address import Address
from pants.core.util_rules import system_binaries
from pants.core.util_rules.archive import ExtractedArchive, MaybeExtractArchiveRequest
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, DigestContents, PathGlobs, RemovePrefix
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, Targets
from pants.jvm.classpath import Classpath
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.key import CoursierResolveKey
from pants.testutil.rule_runner import RuleRunner


def maybe_skip_jdk_test(func):
    run_jdk_tests = bool(ast.literal_eval(os.environ.get("PANTS_RUN_JDK_TESTS", "True")))
    return pytest.mark.skipif(not run_jdk_tests, reason="Skip JDK tests")(func)


def expect_single_expanded_coarsened_target(
    rule_runner: RuleRunner, address: Address
) -> CoarsenedTarget:
    expanded_target = rule_runner.request(Targets, [Addresses([address])]).expect_single()
    coarsened_targets = rule_runner.request(
        CoarsenedTargets, [Addresses([expanded_target.address])]
    )
    assert len(coarsened_targets) == 1
    return coarsened_targets[0]


def make_resolve(
    rule_runner: RuleRunner,
    resolve_name: str = "jvm-default",
    resolve_path: str = "3rdparty/jvm/default.lock",
) -> CoursierResolveKey:
    digest = rule_runner.request(Digest, [PathGlobs([resolve_path])])
    return CoursierResolveKey(name=resolve_name, path=resolve_path, digest=digest)


@dataclass(frozen=True)
class RenderedClasspath:
    """The contents of a classpath, organized as a key per entry with its contained classfiles."""

    content: dict[str, set[str]]


@rule
async def render_classpath_entry(
    classpath_entry: ClasspathEntry, unzip_binary: UnzipBinary
) -> RenderedClasspath:
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
                input_digest=classpath_entry.digest,
                output_directories=(dest_dir,),
                description=f"Extract {filename}",
            ),
        )
        for filename in classpath_entry.filenames
    )

    listing_snapshots = await MultiGet(
        Get(Snapshot, RemovePrefix(pr.output_digest, dest_dir)) for pr in process_results
    )

    return RenderedClasspath(
        {
            path: set(listing.files)
            for path, listing in zip(classpath_entry.filenames, listing_snapshots)
        }
    )


@rule
async def render_classpath(classpath: Classpath) -> RenderedClasspath:
    rendered_classpaths = await MultiGet(
        Get(RenderedClasspath, ClasspathEntry, cpe)
        for cpe in ClasspathEntry.closure(classpath.entries)
    )
    return RenderedClasspath({k: v for rc in rendered_classpaths for k, v in rc.content.items()})


def rules():
    return [
        *collect_rules(),
        *system_binaries.rules(),
        QueryRule(CoarsenedTargets, (Addresses,)),
        QueryRule(RenderedClasspath, (Classpath,)),
        QueryRule(RenderedClasspath, (ClasspathEntry,)),
        QueryRule(Targets, (Addresses,)),
    ]


def _get_jar_contents_snapshot(
    rule_runner: RuleRunner, *, filename: str, digest: Digest
) -> Snapshot:
    contents = rule_runner.request(DigestContents, [digest])
    files_content = [content for content in contents if content.path == filename]
    assert len(files_content) == 1

    renamed_digest = rule_runner.request(
        Digest, [CreateDigest([dataclasses.replace(files_content[0], path=f"{filename}.zip")])]
    )
    extracted_jar = rule_runner.request(
        ExtractedArchive, [MaybeExtractArchiveRequest(renamed_digest)]
    )
    return rule_runner.request(Snapshot, [extracted_jar.digest])
