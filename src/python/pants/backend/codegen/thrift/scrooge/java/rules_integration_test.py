# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.thrift.rules import rules as thrift_rules
from pants.backend.codegen.thrift.scrooge.java.rules import GenerateJavaFromThriftRequest
from pants.backend.codegen.thrift.scrooge.java.rules import rules as scrooge_java_rules
from pants.backend.codegen.thrift.scrooge.rules import rules as scrooge_rules
from pants.backend.codegen.thrift.target_types import (
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
)
from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.backend.scala import target_types
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.jvm import classpath, testutil
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *thrift_rules(),
            *scrooge_rules(),
            *scrooge_java_rules(),
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *strip_jar.rules(),
            *scalac_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *stripped_source_files.rules(),
            *artifact_mapper.rules(),
            *javac_rules(),
            *java_dep_inf_rules(),
            *testutil.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromThriftRequest]),
            QueryRule(RenderedClasspath, (CompileJavaSourceRequest,)),
            QueryRule(Addresses, (DependenciesRequest,)),
        ],
        target_types=[
            JvmArtifactTarget,
            JavaSourceTarget,
            JavaSourcesGeneratorTarget,
            ThriftSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


@pytest.fixture
def scrooge_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scrooge.test.lock",
        ["org.apache.thrift:libthrift:0.15.0", "com.twitter:scrooge-core_2.13:21.12.0"],
    )


@pytest.fixture
def scrooge_lockfile(
    scrooge_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scrooge_lockfile_def.load(request)


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
    thrift_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ThriftSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateJavaFromThriftRequest(thrift_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


@logging
def test_generates_java(rule_runner: RuleRunner, scrooge_lockfile: JVMLockfileFixture) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Thrift files can import other thrift files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    #  * Dependency inference between Java and Thrift sources.
    rule_runner.write_files(
        {
            "src/thrift/dir1/f.thrift": dedent(
                """\
                namespace java org.pantsbuild.example
                struct Person {
                  1: string name
                  2: i32 id
                  3: string email
                }
                """
            ),
            "src/thrift/dir1/f2.thrift": dedent(
                """\
                namespace java org.pantsbuild.example.mngt
                include "dir1/f.thrift"
                struct ManagedPerson {
                  1: f.Person employee
                  2: f.Person manager
                }
                """
            ),
            "src/thrift/dir1/BUILD": "thrift_sources()",
            "src/thrift/dir2/g.thrift": dedent(
                """\
                namespace java org.pantsbuild.example.wrapper
                include "dir1/f2.thrift"
                struct ManagedPersonWrapper {
                  1: f2.ManagedPerson managed_person
                }
                """
            ),
            "src/thrift/dir2/BUILD": "thrift_sources(dependencies=['src/thrift/dir1'])",
            # Test another source root.
            "tests/thrift/test_thrifts/f.thrift": dedent(
                """\
                namespace java org.pantsbuild.example.test
                include "dir2/g.thrift"
                struct Executive {
                  1: g.ManagedPersonWrapper managed_person_wrapper
                }
                """
            ),
            "tests/thrift/test_thrifts/BUILD": "thrift_sources(dependencies=['src/thrift/dir2'])",
            "3rdparty/jvm/default.lock": scrooge_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scrooge_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "java_sources()",
            "src/jvm/TestScroogeThriftJava.java": dedent(
                """\
                package org.pantsbuild.example;
                public class TestScroogeThriftJava {
                    Person person;
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: list[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/python", "/src/thrift", "/tests/thrift"],
            expected_files=expected,
        )

    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f.thrift"),
        [
            "src/thrift/org/pantsbuild/example/Person.java",
        ],
    )
    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f2.thrift"),
        [
            "src/thrift/org/pantsbuild/example/mngt/ManagedPerson.java",
        ],
    )
    assert_gen(
        Address("src/thrift/dir2", relative_file_path="g.thrift"),
        [
            "src/thrift/org/pantsbuild/example/wrapper/ManagedPersonWrapper.java",
        ],
    )
    assert_gen(
        Address("tests/thrift/test_thrifts", relative_file_path="f.thrift"),
        [
            "tests/thrift/org/pantsbuild/example/test/Executive.java",
        ],
    )

    tgt = rule_runner.get_target(
        Address("src/jvm", relative_file_path="TestScroogeThriftJava.java")
    )
    dependencies = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
    assert Address("src/thrift/dir1", relative_file_path="f.thrift") in dependencies

    request = CompileJavaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    _ = rule_runner.request(RenderedClasspath, [request])
