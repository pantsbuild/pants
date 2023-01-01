# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.util_rules.archive import ExtractedArchive, MaybeExtractArchiveRequest
from pants.core.util_rules.archive import rules as archive_rules
from pants.core.util_rules.system_binaries import BashBinary, UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.jvm import jdk_rules
from pants.jvm.classpath import Classpath
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_test_util import EMPTY_JVM_LOCKFILE
from pants.jvm.strip_jar import strip_jar
from pants.jvm.strip_jar.strip_jar import StripJarRequest
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.logging import LogLevel


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *classpath_rules(),
            *archive_rules(),
            *strip_jar.rules(),
            *jvm_tool.rules(),
            *graph_rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *java_dep_inf_rules(),
            *target_types_rules(),
            *util_rules(),
            QueryRule(BashBinary, ()),
            QueryRule(UnzipBinary, ()),
            QueryRule(ExtractedArchive, (MaybeExtractArchiveRequest,)),
            QueryRule(ProcessResult, (Process,)),
            QueryRule(Classpath, (Addresses,)),
            QueryRule(Digest, (StripJarRequest,)),
        ],
        target_types=[
            JavaSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


JAVA_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example;

    public class Example {
        public static void main(String[] args) {
            System.out.println("Hello, World!");
        }
    }
    """
)


@maybe_skip_jdk_test
def test_strip_jar(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                    java_sources(
                        name="example",
                    )
                """
            ),
            "3rdparty/jvm/default.lock": EMPTY_JVM_LOCKFILE,
            "Example.java": JAVA_MAIN_SOURCE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="example"))
    classpath = rule_runner.request(Classpath, [Addresses((tgt.address,))])

    jar = rule_runner.request(Digest, [MergeDigests([*classpath.digests()])])
    stripped_jar = rule_runner.request(Digest, [StripJarRequest(jar, tuple(classpath.args()))])
    snapshot = rule_runner.request(Snapshot, [stripped_jar])

    assert len(snapshot.files) == 1

    filename = snapshot.files[0]
    bash = rule_runner.request(BashBinary, [])
    unzip = rule_runner.request(UnzipBinary, [])

    process_result = rule_runner.request(
        ProcessResult,
        [
            Process(
                argv=[
                    bash.path,
                    "-c",
                    f"{unzip.path} -qq {filename} && /bin/date -Idate -r org/pantsbuild/example/Example.class",
                ],
                input_digest=stripped_jar,
                description="Unzip jar and get date of classfile",
                level=LogLevel.TRACE,
            )
        ],
    )

    assert process_result.stdout.decode() == "2000-01-01\n"
