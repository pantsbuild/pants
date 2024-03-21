# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.dependency_inference import rules as scala_dep_inf_rules
from pants.backend.scala.resolve.lockfile import rules as scala_lockfile_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.core.goals.generate_lockfiles import GenerateLockfileResult
from pants.core.goals.resolve_helpers import UserGenerateLockfiles
from pants.core.util_rules import external_tool, source_files, system_binaries
from pants.engine.internals import build_files, graph
from pants.jvm import jdk_rules
from pants.jvm.goals import lockfile
from pants.jvm.goals.lockfile import GenerateJvmLockfile, RequestedJVMUserResolveNames
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import rules as coursier_jvm_tool_rules
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *scala_lockfile_rules(),
            *scala_dep_inf_rules.rules(),
            *jdk_rules.rules(),
            *coursier_fetch_rules(),
            *coursier_jvm_tool_rules(),
            *lockfile.rules(),
            *coursier_setup_rules(),
            *external_tool.rules(),
            *source_files.rules(),
            *util_rules(),
            *system_binaries.rules(),
            *graph.rules(),
            *build_files.rules(),
            *target_types.rules(),
            QueryRule(UserGenerateLockfiles, (RequestedJVMUserResolveNames,)),
            QueryRule(GenerateLockfileResult, (GenerateJvmLockfile,)),
        ],
        target_types=[JvmArtifactTarget, ScalaSourceTarget, ScalaSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        [
            '--scala-version-for-resolve={"foo":"2.13.8"}',
            '--jvm-resolves={"foo": "foo/foo.lock"}',
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


@maybe_skip_jdk_test
def test_missing_scala_library_triggers_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "scala_sources(resolve='foo')",
            "foo/Foo.scala": "package foo",
        }
    )

    with engine_error(ValueError, contains="does not contain a requirement for the Scala runtime"):
        _ = rule_runner.request(
            UserGenerateLockfiles,
            [RequestedJVMUserResolveNames(["foo"])],
        )


@maybe_skip_jdk_test
def test_conflicting_scala_library_triggers_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": textwrap.dedent(
                """\
                scala_sources(resolve='foo')
                jvm_artifact(
                  name="org.scala-lang_scala-library_2.13.1",
                  group="org.scala-lang",
                  artifact="scala-library",
                  version="2.13.1",
                  resolve="foo",
                )
                """
            ),
            "foo/Foo.scala": "package foo",
        }
    )

    with engine_error(
        ValueError,
        contains="The JVM resolve `foo` contains a `jvm_artifact` for version 2.13.1 of the Scala runtime",
    ):
        _ = rule_runner.request(
            UserGenerateLockfiles,
            [RequestedJVMUserResolveNames(["foo"])],
        )
