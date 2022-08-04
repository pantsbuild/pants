# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.protobuf.kotlin.rules import GenerateKotlinFromProtobufRequest
from pants.backend.codegen.protobuf.kotlin.rules import rules as kotlin_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as target_types_rules
from pants.backend.experimental.kotlin.register import rules as kotlin_backend_rules
from pants.backend.kotlin.compile.kotlinc import CompileKotlinSourceRequest
from pants.backend.kotlin.compile.kotlinc_test import KOTLIN_STDLIB_REQUIREMENTS
from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget, KotlinSourceTarget
from pants.engine.addresses import Address
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm import testutil
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, logging


@pytest.fixture
def protobuf_kotlin_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "protobuf-kotlin.test.lock",
        ["com.google.protobuf:protobuf-kotlin:3.19.4", *KOTLIN_STDLIB_REQUIREMENTS],
    )


@pytest.fixture
def protobuf_kotlin_lockfile(
    protobuf_kotlin_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return protobuf_kotlin_lockfile_def.load(request)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *kotlin_backend_rules(),
            *kotlin_protobuf_rules(),
            *target_types_rules(),
            *testutil.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateKotlinFromProtobufRequest]),
            QueryRule(RenderedClasspath, (CompileKotlinSourceRequest,)),
        ],
        target_types=[
            ProtobufSourcesGeneratorTarget,
            KotlinSourceTarget,
            KotlinSourcesGeneratorTarget,
            JvmArtifactTarget,
        ],
    )


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: list[str] | None = None,
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *(extra_args or ())]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateKotlinFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


@logging
def test_generates_kotlin(
    rule_runner: RuleRunner, protobuf_kotlin_lockfile: JVMLockfileFixture
) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Protobuf files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";
                option java_package = "org.pantsbuild.kotlin.proto";

                package dir1;

                message Person {
                  string name = 1;
                  int32 id = 2;
                  string email = 3;
                }
                """
            ),
            "src/protobuf/dir1/f2.proto": dedent(
                """\
                syntax = "proto3";

                package dir1;
                """
            ),
            "src/protobuf/dir1/BUILD": "protobuf_sources()",
            "src/protobuf/dir2/f.proto": dedent(
                """\
                syntax = "proto3";

                package dir2;

                import "dir1/f.proto";
                """
            ),
            "src/protobuf/dir2/BUILD": "protobuf_sources(dependencies=['src/protobuf/dir1'])",
            # Test another source root.
            "tests/protobuf/test_protos/f.proto": dedent(
                """\
                syntax = "proto3";

                package test_protos;

                import "dir2/f.proto";
                """
            ),
            "tests/protobuf/test_protos/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir2'])"
            ),
            "3rdparty/jvm/default.lock": protobuf_kotlin_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": protobuf_kotlin_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "kotlin_sources(dependencies=['src/protobuf/dir1'])",
            "src/jvm/TestKotlinProtobuf.kt": dedent(
                """\
                package org.pantsbuild.kotlin.example;
                import org.pantsbuild.kotlin.proto.F.Person;
                fun main() {
                  val person = Person()
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected_files: list[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/jvm", "/src/protobuf", "/tests/protobuf"],
            expected_files=expected_files,
        )

    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        [
            "src/protobuf/org/pantsbuild/kotlin/proto/F.java",
            "src/protobuf/org/pantsbuild/kotlin/proto/FKt.kt",
            "src/protobuf/org/pantsbuild/kotlin/proto/PersonKt.kt",
        ],
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"),
        ["src/protobuf/dir1/F2.java", "src/protobuf/dir1/F2Kt.kt"],
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f.proto"),
        ["src/protobuf/dir2/F.java", "src/protobuf/dir2/FKt.kt"],
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        ["tests/protobuf/test_protos/F.java", "tests/protobuf/test_protos/FKt.kt"],
    )

    request = CompileKotlinSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    _ = rule_runner.request(RenderedClasspath, [request])
