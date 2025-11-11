# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import (
    InferJavaSourceDependencies,
    JavaInferredDependencies,
    JavaInferredDependenciesAndExportsRequest,
    JavaSourceDependenciesInferenceFieldSet,
)
from pants.backend.java.dependency_inference.rules import rules as dep_inference_rules
from pants.backend.java.target_types import (
    JavaSourceField,
    JavaSourcesGeneratorTarget,
    JunitTestsGeneratorTarget,
)
from pants.backend.java.target_types import rules as java_target_rules
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferredDependencies,
    Targets,
)
from pants.jvm.jdk_rules import rules as java_util_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.test.junit import rules as junit_rules
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
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
            *junit_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ExplicitlyProvidedDependencies, [DependenciesRequest]),
            QueryRule(InferredDependencies, [InferJavaSourceDependencies]),
            QueryRule(JavaInferredDependencies, [JavaInferredDependenciesAndExportsRequest]),
            QueryRule(Targets, [UnparsedAddressInputs]),
        ],
        target_types=[JavaSourcesGeneratorTarget, JunitTestsGeneratorTarget, JvmArtifactTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_infer_java_imports_same_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 't',

                )
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

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([])

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])


@maybe_skip_jdk_test
def test_infer_java_imports(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'a',

                )
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
                java_sources(
                    name = 'b',

                )
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
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([target_b.address])

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])


@maybe_skip_jdk_test
def test_infer_java_imports_with_cycle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'a',

                )
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
                java_sources(
                    name = 'b',

                )
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
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([target_b.address])

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([target_a.address])


@maybe_skip_jdk_test
def test_infer_java_imports_ambiguous(rule_runner: RuleRunner, caplog) -> None:
    ambiguous_source = dedent(
        """\
                package org.pantsbuild.a;
                public class A {}
                """
    )
    rule_runner.write_files(
        {
            "a_one/BUILD": "java_sources()",
            "a_one/A.java": ambiguous_source,
            "a_two/BUILD": "java_sources()",
            "a_two/A.java": ambiguous_source,
            "b/BUILD": "java_sources()",
            "b/B.java": dedent(
                """\
                package org.pantsbuild.b;
                import org.pantsbuild.a.A;
                public class B {}
                """
            ),
            "c/BUILD": dedent(
                """\
                java_sources(
                  dependencies=["!a_two/A.java"],
                )
                """
            ),
            "c/C.java": dedent(
                """\
                package org.pantsbuild.c;
                import org.pantsbuild.a.A;
                public class C {}
                """
            ),
        }
    )
    target_b = rule_runner.get_target(Address("b", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("c", relative_file_path="C.java"))

    # Because there are two sources of `org.pantsbuild.a.A`, neither should be inferred for B. But C
    # disambiguates with a `!`, and so gets the appropriate version.
    caplog.clear()
    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([])
    assert len(caplog.records) == 1
    assert (
        "The target b/B.java imports `org.pantsbuild.a.A`, but Pants cannot safely" in caplog.text
    )

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_c))],
    ) == InferredDependencies([Address("a_one", relative_file_path="A.java")])


@maybe_skip_jdk_test
def test_infer_java_imports_unnamed_package(rule_runner: RuleRunner) -> None:
    # A source file without a package declaration lives in the "unnamed package", but may still be
    # consumed (but not `import`ed) by other files in the unnamed package.
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name = 'a')
                """
            ),
            "Main.java": dedent(
                """\
                public class Main {
                    public static void main(String[] args) throws Exception {
                        Lib l = new Lib();
                    }
                }
                """
            ),
            "Lib.java": dedent(
                """\
                public class Lib {}
                """
            ),
        }
    )
    target_a = rule_runner.get_target(Address("", target_name="a", relative_file_path="Main.java"))

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([Address("", target_name="a", relative_file_path="Lib.java")])


@maybe_skip_jdk_test
def test_infer_java_imports_same_target_with_cycle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 't',

                )
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
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    ) == InferredDependencies([target_b.address])

    assert rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_b))],
    ) == InferredDependencies([target_a.address])


@maybe_skip_jdk_test
def test_dependencies_from_inferred_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 't',

                )
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

    # Neither //:t nor either of its source subtargets have explicitly provided deps
    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_t.get(Dependencies))]
        ).includes
        == FrozenOrderedSet()
    )
    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_a.get(Dependencies))]
        ).includes
        == FrozenOrderedSet()
    )
    assert (
        rule_runner.request(
            ExplicitlyProvidedDependencies, [DependenciesRequest(target_b.get(Dependencies))]
        ).includes
        == FrozenOrderedSet()
    )

    # //:t has an automatic dependency on each of its subtargets
    assert rule_runner.request(
        Addresses, [DependenciesRequest(target_t.get(Dependencies))]
    ) == Addresses(
        [
            target_a.address,
            target_b.address,
        ]
    )

    # A.java has an inferred dependency on B.java
    assert rule_runner.request(
        Addresses, [DependenciesRequest(target_a.get(Dependencies))]
    ) == Addresses([target_b.address])

    # B.java does NOT have a dependency on A.java, as it would if we just had subtargets without
    # inferred dependencies.
    assert (
        rule_runner.request(Addresses, [DependenciesRequest(target_b.get(Dependencies))])
        == Addresses()
    )


@maybe_skip_jdk_test
def test_package_private_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 't',

                )
                """
            ),
            "A.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.pantsbuild.example.C;

                public class A {
                    public static void main(String[] args) throws Exception {
                        C c = new C();
                    }
                }
                """
            ),
            "B.java": dedent(
                """\
                package org.pantsbuild.example;

                public class B {}

                class C {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.java"))

    # A.java has an inferred dependency on B.java
    assert rule_runner.request(
        Addresses, [DependenciesRequest(target_a[Dependencies])]
    ) == Addresses([target_b.address])

    # B.java does NOT have a dependency on A.java, as it would if we just had subtargets without
    # inferred dependencies.
    assert (
        rule_runner.request(Addresses, [DependenciesRequest(target_b[Dependencies])]) == Addresses()
    )


@maybe_skip_jdk_test
def test_junit_test_dep(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'lib',

                )
                junit_tests(
                    name = 'tests',

                )
                """
            ),
            "FooTest.java": dedent(
                """\
                package org.pantsbuild.example;

                import org.pantsbuild.example.C;

                public class FooTest {
                    public static void main(String[] args) throws Exception {
                        C c = new C();
                    }
                }
                """
            ),
            "Foo.java": dedent(
                """\
                package org.pantsbuild.example;

                public class Foo {}

                class C {}
                """
            ),
        }
    )

    lib = rule_runner.get_target(Address("", target_name="lib", relative_file_path="Foo.java"))
    tests = rule_runner.get_target(
        Address("", target_name="tests", relative_file_path="FooTest.java")
    )

    # A.java has an inferred dependency on B.java
    assert rule_runner.request(Addresses, [DependenciesRequest(tests[Dependencies])]) == Addresses(
        [lib.address]
    )

    # B.java does NOT have a dependency on A.java, as it would if we just had subtargets without
    # inferred dependencies.
    assert rule_runner.request(Addresses, [DependenciesRequest(lib[Dependencies])]) == Addresses()


@maybe_skip_jdk_test
def test_exports(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 't',

                )
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

                import org.pantsbuild.c.C;
                import org.pantsbuild.d.D;

                public class B extends C {}
                """
            ),
            "C.java": dedent(
                """\
                package org.pantsbuild.c;

                public class C {}
                """
            ),
            "D.java": dedent(
                """\
                package org.pantsbuild.d;

                public class D {}
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="t", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="t", relative_file_path="B.java"))

    # B should depend on C and D, but only export C
    assert rule_runner.request(
        JavaInferredDependencies,
        [JavaInferredDependenciesAndExportsRequest(target_b[JavaSourceField])],
    ) == JavaInferredDependencies(
        dependencies=FrozenOrderedSet(
            [
                Address("", target_name="t", relative_file_path="C.java"),
                Address("", target_name="t", relative_file_path="D.java"),
            ]
        ),
        exports=FrozenOrderedSet(
            [
                Address("", target_name="t", relative_file_path="C.java"),
            ]
        ),
    )

    # A should depend on B, but not B's dependencies or export types
    assert rule_runner.request(
        JavaInferredDependencies,
        [JavaInferredDependenciesAndExportsRequest(target_a[JavaSourceField])],
    ) == JavaInferredDependencies(
        dependencies=FrozenOrderedSet(
            [
                Address("", target_name="t", relative_file_path="B.java"),
            ]
        ),
        exports=FrozenOrderedSet([]),
    )
