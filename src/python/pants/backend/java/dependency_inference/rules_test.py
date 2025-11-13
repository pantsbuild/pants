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

    # B should depend on C and D.
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
    )

    # A should depend on B, but not B's dependencies
    assert rule_runner.request(
        JavaInferredDependencies,
        [JavaInferredDependenciesAndExportsRequest(target_a[JavaSourceField])],
    ) == JavaInferredDependencies(
        dependencies=FrozenOrderedSet(
            [
                Address("", target_name="t", relative_file_path="B.java"),
            ]
        ),
    )


@maybe_skip_jdk_test
def test_infer_same_package_inner_class(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "java_sources(name='lib')",
            "B.java": dedent(
                """\
                package com.example;
                public class B {
                    public static class InnerB {
                        public void hello() {}
                    }
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;
                public class A {
                    private B.InnerB inner;

                    public void use() {
                        inner = new B.InnerB();
                        inner.hello();
                    }
                }
                """
            ),
        }
    )

    a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))

    # A should depend on B due to B.InnerB reference
    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(a))],
    )
    assert inferred == InferredDependencies([b.address])


@maybe_skip_jdk_test
def test_infer_same_package_deeply_nested_inner_class(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "java_sources(name='lib')",
            "Outer.java": dedent(
                """\
                package com.example;
                public class Outer {
                    public static class Middle {
                        public static class Inner {
                            public void hello() {}
                        }
                    }
                }
                """
            ),
            "Consumer.java": dedent(
                """\
                package com.example;
                public class Consumer {
                    public void use() {
                        Outer.Middle.Inner obj = new Outer.Middle.Inner();
                    }
                }
                """
            ),
        }
    )

    consumer = rule_runner.get_target(Address("", target_name="lib", relative_file_path="Consumer.java"))
    outer = rule_runner.get_target(Address("", target_name="lib", relative_file_path="Outer.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(consumer))],
    )
    assert inferred == InferredDependencies([outer.address])


@maybe_skip_jdk_test
def test_infer_imported_outer_class_inner_ref(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "pkg1/BUILD": "java_sources()",
            "pkg1/B.java": dedent(
                """\
                package com.pkg1;
                public class B {
                    public static class InnerB {}
                }
                """
            ),
            "pkg2/BUILD": "java_sources()",
            "pkg2/A.java": dedent(
                """\
                package com.pkg2;

                import com.pkg1.B;

                public class A {
                    B.InnerB obj;
                }
                """
            ),
        }
    )

    a = rule_runner.get_target(Address("pkg2", relative_file_path="A.java"))
    b = rule_runner.get_target(Address("pkg1", relative_file_path="B.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(a))],
    )
    assert inferred == InferredDependencies([b.address])


@maybe_skip_jdk_test
def test_infer_third_party_with_same_package_refs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/BUILD": dedent(
                """\
                jvm_artifact(
                    name="guava",
                    group="com.google.guava",
                    artifact="guava",
                    version="31.0-jre",
                    packages=["com.google.common.**"],
                )
                """
            ),
            "BUILD": "java_sources(name='lib')",
            "MyClass.java": dedent(
                """\
                package com.example;

                import com.google.common.collect.ImmutableList;

                public class MyClass {
                    private Helper helper;  // Same package, no import
                    private ImmutableList<String> list;  // Third-party, with import

                    // Inline FQTN reference without import
                    private com.google.common.collect.ImmutableMap<String, String> map;
                }
                """
            ),
            "Helper.java": dedent(
                """\
                package com.example;
                public class Helper {}
                """
            ),
        }
    )

    my_class = rule_runner.get_target(Address("", target_name="lib", relative_file_path="MyClass.java"))
    helper = rule_runner.get_target(Address("", target_name="lib", relative_file_path="Helper.java"))
    guava = rule_runner.get_target(Address("3rdparty/jvm", target_name="guava"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(my_class))],
    )

    # Should depend on both same-package Helper and third-party Guava
    assert helper.address in inferred.include
    assert guava.address in inferred.include


@maybe_skip_jdk_test
def test_infer_java_exports_public_static_field(rule_runner: RuleRunner) -> None:
    """Test transitive dependency through public static field.

    A imports B, B has public static field of type C.
    A should transitively depend on C even though A never imports C.
    """
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name='lib')
                """
            ),
            "C.java": dedent(
                """\
                package com.example;

                public abstract class C {
                    public void doThing() { }
                }
                """
            ),
            "B.java": dedent(
                """\
                package com.example;

                public class B {
                    public static C someField = new C() { };
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;

                import com.example.B;  // Only imports B, NOT C!

                public class A {
                    void use() {
                        B.someField.doThing();  // Calls method on C without importing C
                    }
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("", target_name="lib", relative_file_path="C.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    )

    # A should depend on B (direct import).
    # C is NOT inferred as a dependency - it's automatically available on the compilation
    # classpath as a transitive dependency of B.
    assert target_b.address in inferred.include
    assert target_c.address not in inferred.include


@maybe_skip_jdk_test
def test_infer_java_exports_method_return_type(rule_runner: RuleRunner) -> None:
    """Test transitive dependency through method return type.

    A imports B, B has method returning C.
    A should transitively depend on C.
    """
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name='lib')
                """
            ),
            "C.java": dedent(
                """\
                package com.example;

                public class C {
                    public void process() { }
                }
                """
            ),
            "B.java": dedent(
                """\
                package com.example;

                public class B {
                    public C getC() { return new C(); }
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;

                import com.example.B;

                public class A {
                    void use(B b) {
                        b.getC().process();
                    }
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("", target_name="lib", relative_file_path="C.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    )

    # A should depend on B (direct import).
    # C is NOT inferred - it's automatically available on the compilation classpath transitively.
    assert target_b.address in inferred.include
    assert target_c.address not in inferred.include


@maybe_skip_jdk_test
def test_infer_java_exports_method_return_type(rule_runner: RuleRunner) -> None:
    """Test transitive dependency through method parameter type.

    A imports B, B has method taking C as parameter.
    A should transitively depend on C.
    """
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name='lib')
                """
            ),
            "C.java": dedent(
                """\
                package com.example;

                public class C { }
                """
            ),
            "B.java": dedent(
                """\
                package com.example;

                public class B {
                    public void process(C param) { }
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;

                import com.example.B;

                public class A {
                    void use(B b) {
                        b.process(null);
                    }
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("", target_name="lib", relative_file_path="C.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    )

    # A should depend on B (direct import).
    # C is NOT inferred - it's automatically available on the compilation classpath transitively.
    assert target_b.address in inferred.include
    assert target_c.address not in inferred.include


@maybe_skip_jdk_test
def test_infer_java_exports_method_parameter_type(rule_runner: RuleRunner) -> None:
    """Test transitive dependency through superclass.

    A imports B, B extends C.
    A should transitively depend on C.
    """
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name='lib')
                """
            ),
            "C.java": dedent(
                """\
                package com.example;

                public abstract class C {
                    public abstract void doWork();
                }
                """
            ),
            "B.java": dedent(
                """\
                package com.example;

                public class B extends C {
                    @Override
                    public void doWork() { }
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;

                import com.example.B;

                public class A {
                    void use() {
                        B b = new B();
                        b.doWork();
                    }
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("", target_name="lib", relative_file_path="C.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    )

    # A should depend on B (direct import).
    # C is NOT inferred - it's automatically available on the compilation classpath transitively.
    assert target_b.address in inferred.include
    assert target_c.address not in inferred.include


@maybe_skip_jdk_test
def test_infer_java_exports_superclass(rule_runner: RuleRunner) -> None:
    """Test transitive dependency through implemented interface.

    A imports B, B implements C.
    A should transitively depend on C.
    """
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name='lib')
                """
            ),
            "C.java": dedent(
                """\
                package com.example;

                public interface C {
                    void execute();
                }
                """
            ),
            "B.java": dedent(
                """\
                package com.example;

                public class B implements C {
                    @Override
                    public void execute() { }
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;

                import com.example.B;

                public class A {
                    void use() {
                        B b = new B();
                        b.execute();
                    }
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("", target_name="lib", relative_file_path="C.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    )

    # A should depend on B (direct import).
    # C is NOT inferred - it's automatically available on the compilation classpath transitively.
    assert target_b.address in inferred.include
    assert target_c.address not in inferred.include


@maybe_skip_jdk_test
def test_infer_java_exports_interface(rule_runner: RuleRunner) -> None:
    """Test that private fields are NOT exported.

    B has private field of type C. A imports B but should NOT depend on C.
    """
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(name='lib')
                """
            ),
            "C.java": dedent(
                """\
                package com.example;

                public class C { }
                """
            ),
            "B.java": dedent(
                """\
                package com.example;

                public class B {
                    private C privateField;  // Private field - should NOT be exported
                }
                """
            ),
            "A.java": dedent(
                """\
                package com.example;

                import com.example.B;

                public class A {
                    void use() {
                        B b = new B();
                    }
                }
                """
            ),
        }
    )

    target_a = rule_runner.get_target(Address("", target_name="lib", relative_file_path="A.java"))
    target_b = rule_runner.get_target(Address("", target_name="lib", relative_file_path="B.java"))
    target_c = rule_runner.get_target(Address("", target_name="lib", relative_file_path="C.java"))

    inferred = rule_runner.request(
        InferredDependencies,
        [InferJavaSourceDependencies(JavaSourceDependenciesInferenceFieldSet.create(target_a))],
    )

    # A should depend on B (direct import) but NOT on C (private field not exported)
    assert target_b.address in inferred.include
    assert target_c.address not in inferred.include
