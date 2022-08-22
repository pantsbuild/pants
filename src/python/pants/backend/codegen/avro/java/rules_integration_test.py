# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.avro.java.rules import GenerateJavaFromAvroRequest
from pants.backend.codegen.avro.java.rules import rules as avro_java_rules
from pants.backend.codegen.avro.rules import rules as avro_rules
from pants.backend.codegen.avro.target_types import AvroSourceField, AvroSourcesGeneratorTarget
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.goals.check import JavacCheckRequest
from pants.backend.java.goals.check import rules as javac_check_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResult, CheckResults
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.internals import graph
from pants.engine.rules import QueryRule
from pants.engine.target import (
    CoarsenedTargets,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    Targets,
)
from pants.jvm import classpath
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import expect_single_expanded_coarsened_target
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *avro_rules(),
            *avro_java_rules(),
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
            *jdk_rules(),
            *graph.rules(),
            *jvm_compile_rules(),
            *stripped_source_files.rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *javac_check_rules(),
            *java_dep_inf_rules(),
            QueryRule(CheckResults, (JavacCheckRequest,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(GeneratedSources, [GenerateJavaFromAvroRequest]),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(Targets, (Addresses,)),
        ],
        target_types=[
            JavaSourceTarget,
            JavaSourcesGeneratorTarget,
            AvroSourcesGeneratorTarget,
            JvmArtifactTarget,
        ],
    )
    rule_runner.set_options(
        ["--source-roots=['src/jvm','src/avro']", "-ltrace"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


@pytest.fixture
def avro_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "avro.test.lock",
        ["org.apache.avro:avro:1.11.0", "org.apache.avro:avro-ipc:1.11.0"],
    )


@pytest.fixture
def avro_lockfile(avro_lockfile_def: JVMLockfileFixtureDefinition, request) -> JVMLockfileFixture:
    return avro_lockfile_def.load(request)


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: Iterable[str] = (),
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *extra_args]
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[AvroSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateJavaFromAvroRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


@logging
def test_generates_java_from_avro(
    rule_runner: RuleRunner, avro_lockfile: JVMLockfileFixture
) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Avro files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": avro_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": avro_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "java_sources(dependencies=['src/avro/dir1'])",
            "src/jvm/TestAvro.java": dedent(
                """\
                package org.pantsbuild.example.avro;
                import org.pantsbuild.contrib.avro.User;
                public class TestAvro {
                    User simple;
                }
                """
            ),
            "src/avro/dir1/BUILD": "avro_sources()",
            "src/avro/dir1/simple.avdl": dedent(
                """\
                /**
                 * From https://avro.apache.org/docs/current/idl.html
                 * An example protocol in Avro IDL
                 */
                @namespace("org.pantsbuild.contrib.avro")
                protocol Simple {
                  @aliases(["org.foo.KindOf"])
                  enum Kind {
                    FOO,
                    BAR, // the bar enum value
                    BAZ
                  }

                  fixed MD5(16);

                  record TestRecord {
                    @order("ignore")
                    string name;

                    @order("descending")
                    Kind kind;

                    MD5 hash;

                    union { MD5, null} @aliases(["hash"]) nullableHash;

                    array<long> arrayOfLongs;
                  }

                  error TestError {
                    string message;
                  }

                  string hello(string greeting);
                  TestRecord echo(TestRecord `record`);
                  int add(int arg1, int arg2);
                  bytes echoBytes(bytes data);
                  void `error`() throws TestError;
                  void ping() oneway;
                }
                """
            ),
            "src/avro/dir1/user.avsc": dedent(
                """\
                {"namespace": "org.pantsbuild.contrib.avro",
                 "type": "record",
                 "name": "User",
                 "fields": [
                     {"name": "name", "type": "string"},
                     {"name": "favorite_number",  "type": ["int", "null"]},
                     {"name": "favorite_color", "type": ["string", "null"]}
                 ]
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/jvm", "src/avro"],
            expected_files=list(expected),
        )

    assert_gen(
        Address("src/avro/dir1", relative_file_path="simple.avdl"),
        (
            "src/avro/org/pantsbuild/contrib/avro/Kind.java",
            "src/avro/org/pantsbuild/contrib/avro/MD5.java",
            "src/avro/org/pantsbuild/contrib/avro/Simple.java",
            "src/avro/org/pantsbuild/contrib/avro/TestError.java",
            "src/avro/org/pantsbuild/contrib/avro/TestRecord.java",
        ),
    )
    assert_gen(
        Address("src/avro/dir1", relative_file_path="user.avsc"),
        ["src/avro/org/pantsbuild/contrib/avro/User.java"],
    )

    ct = expect_single_expanded_coarsened_target(rule_runner, Address("src/jvm"))
    check_results = rule_runner.request(
        CheckResults,
        [JavacCheckRequest([JavacCheckRequest.field_set_type.create(ct.representative)])],
    ).results
    assert set(check_results) == {CheckResult(0, "", "")}
