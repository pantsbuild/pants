# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget
from pants.backend.java.target_types import rules as java_target_rules
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.target import Dependencies, DependenciesRequest
from pants.jvm.dependency_inference.artifact_mapper import (
    FrozenTrieNode,
    ThirdPartyPackageToArtifactMapping,
    UnversionedCoordinate,
)
from pants.jvm.jdk_rules import rules as java_util_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifact
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

NAMED_RESOLVE_OPTIONS = '--jvm-resolves={"test": "coursier_resolve.lockfile"}'
DEFAULT_RESOLVE_OPTION = "--jvm-default-resolve=test"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *dep_inference_rules(),
            *external_tool_rules(),
            *java_target_rules(),
            *java_util_rules(),
            *javac_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ThirdPartyPackageToArtifactMapping, []),
        ],
        target_types=[JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget, JvmArtifact],
    )
    rule_runner.set_options(
        args=[NAMED_RESOLVE_OPTIONS, DEFAULT_RESOLVE_OPTION], env_inherit=PYTHON_BOOTSTRAP_ENV
    )
    return rule_runner


@maybe_skip_jdk_test
def test_third_party_mapping_parsing(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--java-infer-third-party-import-mapping={'io.github.frenchtoast.savory.**': 'github-frenchtoast:savory'}"
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    mapping = rule_runner.request(ThirdPartyPackageToArtifactMapping, [])
    root_node = mapping.mapping_root

    # Handy trie traversal function to placate mypy
    def traverse(*children) -> FrozenTrieNode:
        node = root_node
        for child in children:
            new_node = node.find_child(child)
            if not new_node:
                coord = ".".join(children)
                raise Exception(f"Could not find the package specifed by {coord}.")
            node = new_node
        return node

    # Verify some provided by `JVM_ARTFACT_MAPPINGS`
    assert set(traverse("org", "junit").coordinates) == {
        UnversionedCoordinate(group="junit", artifact="junit")
    }
    assert set(traverse("org", "aopalliance").coordinates) == {
        UnversionedCoordinate(group="aopalliance", artifact="aopalliance")
    }

    # Verify the one that we provided in the options is there too.
    assert set(traverse("io", "github", "frenchtoast", "savory").coordinates) == {
        UnversionedCoordinate(group="github-frenchtoast", artifact="savory")
    }


@maybe_skip_jdk_test
def test_third_party_dep_inference(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--java-infer-third-party-import-mapping={'org.joda.time.**': 'joda-time:joda-time'}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )

                java_sources(name = 'lib')
                """
            ),
            "PrintDate.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.joda.time.DateTime;

                public class PrintDate {
                    public static void main(String[] args) {
                        DateTime dt = new DateTime();
                        System.out.println(dt.toString());
                    }
                }
                """
            ),
        }
    )

    lib = rule_runner.get_target(
        Address("", target_name="lib", relative_file_path="PrintDate.java")
    )
    assert rule_runner.request(Addresses, [DependenciesRequest(lib[Dependencies])]) == Addresses(
        [Address("", target_name="joda-time_joda-time")]
    )


@maybe_skip_jdk_test
def test_third_party_dep_inference_fqtn(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--java-infer-third-party-import-mapping={'org.joda.time.**': 'joda-time:joda-time'}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )

                java_sources(name = 'lib')
                """
            ),
            "PrintDate.java": dedent(
                """\
                package org.pantsbuild.example;

                public class PrintDate {
                    public static void main(String[] args) {
                        org.joda.time.DateTime dt = new DateTime();
                        System.out.println(dt.toString());
                    }
                }
                """
            ),
        }
    )

    lib = rule_runner.get_target(
        Address("", target_name="lib", relative_file_path="PrintDate.java")
    )
    assert rule_runner.request(Addresses, [DependenciesRequest(lib[Dependencies])]) == Addresses(
        [Address("", target_name="joda-time_joda-time")]
    )


@maybe_skip_jdk_test
def test_third_party_dep_inference_nonrecursive(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--java-infer-third-party-import-mapping={'org.joda.time.**':'joda-time:joda-time', 'org.joda.time.DateTime':'joda-time:joda-time-2'}"
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )

                jvm_artifact(
                    name = "joda-time_joda-time-2",
                    group = "joda-time",
                    artifact = "joda-time-2",  # doesn't really exist, but useful for this test
                    version = "2.10.10",
                )

                java_sources(name = 'lib')
                """
            ),
            "PrintDate.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.joda.time.DateTime;

                public class PrintDate {
                    public static void main(String[] args) {
                        DateTime dt = new DateTime();
                        System.out.println(dt.toString());
                    }
                }
                """
            ),
            "PrintDate2.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.joda.time.LocalDateTime;

                public class PrintDate {
                    public static void main(String[] args) {
                        DateTime dt = new LocalDateTime();
                        System.out.println(dt.toString());
                    }
                }
                """
            ),
        }
    )

    # First test whether the specific import mapping for org.joda.time.DateTime takes effect over the recursive
    # mapping.
    lib1 = rule_runner.get_target(
        Address("", target_name="lib", relative_file_path="PrintDate.java")
    )
    assert rule_runner.request(Addresses, [DependenciesRequest(lib1[Dependencies])]) == Addresses(
        [Address("", target_name="joda-time_joda-time-2")]
    )

    # Then try a file which should not match the specific import mapping and which will then match the
    # recursive mapping.
    lib2 = rule_runner.get_target(
        Address("", target_name="lib", relative_file_path="PrintDate2.java")
    )
    assert rule_runner.request(Addresses, [DependenciesRequest(lib2[Dependencies])]) == Addresses(
        [Address("", target_name="joda-time_joda-time")]
    )
