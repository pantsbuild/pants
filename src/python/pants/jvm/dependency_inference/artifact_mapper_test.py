# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.java.target_types import (
    JavaSourcesGeneratorTarget,
    JavaSourceTarget,
    JunitTestsGeneratorTarget,
)
from pants.backend.java.target_types import rules as java_target_rules
from pants.core.util_rules import config_files, source_files, system_binaries
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.parametrize import Parametrize
from pants.engine.target import Dependencies, DependenciesRequest
from pants.jvm.dependency_inference.artifact_mapper import (
    DEFAULT_SYMBOL_NAMESPACE,
    FrozenTrieNode,
    MutableTrieNode,
    ThirdPartySymbolMapping,
)
from pants.jvm.dependency_inference.symbol_mapper import JvmFirstPartyPackageMappingException
from pants.jvm.jdk_rules import rules as java_util_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, engine_error
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *jvm_tool.rules(),
            *dep_inference_rules(),
            *java_target_rules(),
            *java_util_rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *source_files.rules(),
            *system_binaries.rules(),
            *util_rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ThirdPartySymbolMapping, []),
        ],
        objects={"parametrize": Parametrize},
        target_types=[
            JavaSourceTarget,
            JavaSourcesGeneratorTarget,
            JunitTestsGeneratorTarget,
            JvmArtifactTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_trie_node_merge_basic() -> None:
    one = MutableTrieNode()
    one.insert("a/b/c", [Address("1")], recursive=True, first_party=False)
    one.insert("a/b/c/d", [Address("2")], recursive=False, first_party=False)
    two = MutableTrieNode()
    two.insert("a/b/c/d", [Address("3")], recursive=False, first_party=False)

    merged = FrozenTrieNode.merge([one.frozen(), two.frozen()])
    assert list(merged) == [
        (
            "a/b/c",
            True,
            FrozenDict({DEFAULT_SYMBOL_NAMESPACE: FrozenOrderedSet([Address("1")])}),
            False,
        ),
        (
            "a/b/c/d",
            False,
            FrozenDict({DEFAULT_SYMBOL_NAMESPACE: FrozenOrderedSet([Address("2"), Address("3")])}),
            False,
        ),
    ]


@maybe_skip_jdk_test
def test_third_party_mapping_parsing(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--java-infer-third-party-import-mapping={'io.github.frenchtoast.savory.**': 'github-frenchtoast:savory'}"
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "junit_junit",
                    group = "junit",
                    artifact = "junit",
                    version = "0.0.1",
                )

                jvm_artifact(
                    name = "github-frenchtoast_savory",
                    group = "github-frenchtoast",
                    artifact = "savory",
                    version = "0.0.1",
                )

                jvm_artifact(
                    name = "does.not_exist",
                    group = "does.not",
                    artifact = "exist",
                    version = "0.0.1",
                    packages = ["but.let.us.pretend.**"],
                )

                jvm_artifact(
                    name = "is.a.total_mystery",
                    group = "is.a.total",
                    artifact = "mystery",
                    version = "0.0.1",
                )
                """
            ),
        }
    )

    mapping = rule_runner.request(ThirdPartySymbolMapping, [])
    root_node = mapping["jvm-default"]

    # Handy trie traversal function to placate mypy
    def traverse(*children) -> FrozenTrieNode:
        node = root_node
        for child in children:
            new_node = node.find_child(child)
            if not new_node:
                coord = ".".join(children)
                raise Exception(f"Could not find the package specified by {coord}.")
            node = new_node
        return node

    # Provided by `JVM_ARTIFACT_MAPPINGS.`
    assert set(traverse("org", "junit").addresses[DEFAULT_SYMBOL_NAMESPACE]) == {
        Address("", target_name="junit_junit"),
    }

    # Provided by options.
    assert set(
        traverse("io", "github", "frenchtoast", "savory").addresses[DEFAULT_SYMBOL_NAMESPACE]
    ) == {
        Address("", target_name="github-frenchtoast_savory"),
    }

    # Provided on the `jvm_artifact`.
    assert set(traverse("but", "let", "us", "pretend").addresses[DEFAULT_SYMBOL_NAMESPACE]) == {
        Address("", target_name="does.not_exist"),
    }

    # Defaulting to the `group`.
    assert set(traverse("is", "a", "total").addresses[DEFAULT_SYMBOL_NAMESPACE]) == {
        Address("", target_name="is.a.total_mystery"),
    }


@maybe_skip_jdk_test
def test_third_party_dep_inference_resolve(rule_runner: RuleRunner) -> None:
    """Dependencies are only resolved on artifacts in the relevant resolves."""
    rule_runner.set_options(
        [
            "--java-infer-third-party-import-mapping={'org.joda.time.**': 'joda-time:joda-time'}",
            "--jvm-resolves={'a': '', 'b': '', 'c': ''}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name="artifact",
                    group="joda-time",
                    artifact="joda-time",
                    version="2.10.10",
                    resolve=parametrize("a", "b", "c"),
                )
                java_source(
                    name="lib",
                    source="PrintDate.java",
                    resolve=parametrize("a", "b", "c"),
                )
                """
            ),
            "PrintDate.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.joda.time.DateTime;
                """
            ),
        }
    )

    def assert_inferred(resolve: str) -> None:
        lib = rule_runner.get_target(
            Address("", target_name="lib", parameters={"resolve": resolve})
        )
        assert rule_runner.request(
            Addresses, [DependenciesRequest(lib[Dependencies])]
        ) == Addresses([Address("", target_name="artifact", parameters={"resolve": resolve})])

    for r in ("a", "b", "c"):
        assert_inferred(r)


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
            "--java-infer-third-party-import-mapping={'org.joda.time.**':'joda-time:joda-time', 'org.joda.time.DateTime':'joda-time:joda-time-2'}",
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


@maybe_skip_jdk_test
def test_third_party_dep_inference_with_provides(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--java-infer-third-party-import-mapping={'org.joda.time.**':'joda-time:joda-time', 'org.joda.time.DateTime':'joda-time:joda-time-2'}",
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

                java_sources(
                    name = 'lib',
                    experimental_provides_types = ['org.joda.time.MefripulousDateTime', ],
                )
                """
            ),
            "PrintDate.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.joda.time.DateTime;
                import org.joda.time.MefripulousDateTime;

                public class PrintDate {
                    public static void main(String[] args) {
                        DateTime dt = new DateTime();
                        System.out.println(dt.toString());
                        new MefripulousDateTime().mefripulate();
                    }
                }
                """
            ),
            "MefripulousDateTime.java": dedent(
                """\
                package org.joda.time;

                public class MefripulousDateTime {
                    public void mefripulate() {
                        DateTime dt = new LocalDateTime();
                        System.out.println(dt.toString());
                    }
                }
                """
            ),
        }
    )

    lib1 = rule_runner.get_target(
        Address("", target_name="lib", relative_file_path="PrintDate.java")
    )
    assert rule_runner.request(Addresses, [DependenciesRequest(lib1[Dependencies])]) == Addresses(
        [
            Address("", target_name="joda-time_joda-time"),
            Address("", target_name="lib", relative_file_path="MefripulousDateTime.java"),
        ]
    )


@maybe_skip_jdk_test
def test_third_party_dep_inference_with_incorrect_provides(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--java-infer-third-party-import-mapping={'org.joda.time.**':'joda-time:joda-time', 'org.joda.time.DateTime':'joda-time:joda-time-2'}",
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

                java_sources(
                    name = 'lib',
                    experimental_provides_types = ['org.joda.time.DateTime', ],
                )
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

    lib1 = rule_runner.get_target(
        Address("", target_name="lib", relative_file_path="PrintDate.java")
    )
    with engine_error(JvmFirstPartyPackageMappingException):
        rule_runner.request(Addresses, [DependenciesRequest(lib1[Dependencies])])
