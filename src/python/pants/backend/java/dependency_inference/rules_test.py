# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.compile.javac_binary import rules as javac_binary_rules
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules
from pants.backend.java.dependency_inference.java_parser_launcher import (
    rules as java_parser_launcher_rules,
)
from pants.backend.java.dependency_inference.rules import InferJavaImportDependencies
from pants.backend.java.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.java.target_types import JavaSourceField, JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as java_target_rules
from pants.backend.java.test.junit import rules as junit_rules
from pants.backend.java.util_rules import rules as java_util_rules
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferredDependencies,
    Targets,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *dep_inference_rules(),
            *external_tool_rules(),
            *java_parser_launcher_rules(),
            *java_parser_rules(),
            *java_target_rules(),
            *java_util_rules(),
            *javac_binary_rules(),
            *javac_rules(),
            *junit_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ExplicitlyProvidedDependencies, [DependenciesRequest]),
            QueryRule(InferredDependencies, [InferJavaImportDependencies]),
            QueryRule(Targets, [UnparsedAddressInputs]),
        ],
        target_types=[JavaSourcesGeneratorTarget],
        bootstrap_args=["--javac-jdk=system"],  # TODO(#12293): use a fixed JDK version.
    )


def test_infer_java_imports_same_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name = 't')
                """
            ),
            "A.java": dedent(
                """\
                package org.pantsbuild.a;

                public class A {}
                """
            ),
            "B.java": dedent(
                """\
                package org.pantsbuild.b;

                public class B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.java"))

    print([target_a, target_b])

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaImportDependencies(target_a[JavaSourceField])],
    ) == InferredDependencies(
        dependencies=[],
        sibling_dependencies_inferrable=True,
    )

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaImportDependencies(target_b[JavaSourceField])],
    ) == InferredDependencies(
        dependencies=[],
        sibling_dependencies_inferrable=True,
    )


def test_infer_java_imports(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name = 'a')
                """
            ),
            "A.java": dedent(
                """\
                package org.pantsbuild.a;

                import org.pantsbuild.b.B;

                public class A {}
                """
            ),
            "sub/BUILD": dedent(
                """\
                java_sources(name = 'b')
                """
            ),
            "sub/B.java": dedent(
                """\
                package org.pantsbuild.b;

                public class B {}
                """
            ),
        }
    )
    target_a = rule_runner.get_target(Address("", target_name="a", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("sub", target_name="b", relative_file_path="B.java"))

    assert rule_runner.request(
        InferredDependencies, [InferJavaImportDependencies(target_a[JavaSourceField])]
    ) == InferredDependencies(
        dependencies=[target_b.address],
        sibling_dependencies_inferrable=True,
    )

    assert rule_runner.request(
        InferredDependencies, [InferJavaImportDependencies(target_b[JavaSourceField])]
    ) == InferredDependencies(
        dependencies=[],
        sibling_dependencies_inferrable=True,
    )


def test_infer_java_imports_with_cycle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name = 'a')
                """
            ),
            "A.java": dedent(
                """\
                package org.pantsbuild.a;

                import org.pantsbuild.b.B;

                public class A {}
                """
            ),
            "sub/BUILD": dedent(
                """\
                java_sources(name = 'b')
                """
            ),
            "sub/B.java": dedent(
                """\
                package org.pantsbuild.b;

                import org.pantsbuild.a.A;

                public class B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="a", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("sub", target_name="b", relative_file_path="B.java"))

    assert rule_runner.request(
        InferredDependencies, [InferJavaImportDependencies(target_a[JavaSourceField])]
    ) == InferredDependencies(
        dependencies=[target_b.address],
        sibling_dependencies_inferrable=True,
    )

    assert rule_runner.request(
        InferredDependencies, [InferJavaImportDependencies(target_b[JavaSourceField])]
    ) == InferredDependencies(
        dependencies=[target_a.address],
        sibling_dependencies_inferrable=True,
    )


def test_infer_java_imports_same_target_with_cycle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name = 't')
                """
            ),
            "A.java": dedent(
                """\
                package org.pantsbuild.a;

                import org.pantsbuild.b.B;

                public class A {}
                """
            ),
            "B.java": dedent(
                """\
                package org.pantsbuild.b;

                import org.pantsbuild.a.A;

                public class B {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.java"))

    assert rule_runner.request(
        InferredDependencies, [InferJavaImportDependencies(target_a[JavaSourceField])]
    ) == InferredDependencies(
        dependencies=[target_b.address],
        sibling_dependencies_inferrable=True,
    )

    assert rule_runner.request(
        InferredDependencies, [InferJavaImportDependencies(target_b[JavaSourceField])]
    ) == InferredDependencies(
        dependencies=[target_a.address],
        sibling_dependencies_inferrable=True,
    )


def test_dependencies_from_inferred_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name = 't')
                """
            ),
            "A.java": dedent(
                """\
                package org.pantsbuild.a;

                import org.pantsbuild.b.B;

                public class A {}
                """
            ),
            "B.java": dedent(
                """\
                package org.pantsbuild.b;

                public class B {}
                """
            ),
        }
    )

    target_t = rule_runner.get_target(Address("", target_name="t"))
    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.java"))

    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_a[Dependencies])]
        ).includes
        == FrozenOrderedSet()
    )

    target_t = rule_runner.get_target(Address("", target_name="t"))

    # Neither //:t nor either of its source subtargets have explicitly provided deps
    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_t[Dependencies])]
        ).includes
        == FrozenOrderedSet()
    )
    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_a[Dependencies])]
        ).includes
        == FrozenOrderedSet()
    )
    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_b[Dependencies])]
        ).includes
        == FrozenOrderedSet()
    )

    # //:t has an automatic dependency on each of its subtargets
    assert rule_runner.request(
        Addresses, [DependenciesRequest(target_t[Dependencies])]
    ) == Addresses(
        [
            target_a.address,
            target_b.address,
        ]
    )

    # A.java has an inferred dependency on B.java
    assert rule_runner.request(
        Addresses, [DependenciesRequest(target_a[Dependencies])]
    ) == Addresses([target_b.address])

    # B.java does NOT have a dependency on A.java, as it would if we just had subtargets without
    # inferred dependencies.
    assert (
        rule_runner.request(Addresses, [DependenciesRequest(target_b[Dependencies])]) == Addresses()
    )
