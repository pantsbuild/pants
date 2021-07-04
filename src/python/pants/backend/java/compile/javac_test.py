# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import CompiledClassfiles, CompileJavaSourceRequest
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.compile.javac_binary import rules as javac_binary_rules
from pants.backend.java.target_types import JavaLibrary
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import DigestContents, FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import CoarsenedTargets, Targets
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    MavenCoord,
    MavenCoordinates,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmDependencyLockfile
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *javac_rules(),
            *util_rules(),
            *javac_binary_rules(),
            QueryRule(CompiledClassfiles, (CompileJavaSourceRequest,)),
            QueryRule(CoarsenedTargets, (Address,)),
        ],
        target_types=[JvmDependencyLockfile, JavaLibrary],
    )


JAVA_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib;

    public class ExampleLib {
        public static String hello() {
            return "Hello!";
        }
    }
    """
)

JAVA_LIB_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example;

    import org.pantsbuild.example.lib.ExampleLib;

    public class Example {
        public static void main(String[] args) {
            System.out.println(ExampleLib.hello());
        }
    }
    """
)


def test_compile_no_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'lib',
                    dependencies = [
                        ':lockfile',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "ExampleLib.java": JAVA_LIB_SOURCE,
        }
    )

    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [
            CompileJavaSourceRequest(
                targets=CoarsenedTargets(
                    [rule_runner.get_target(Address(spec_path="", target_name="lib"))]
                )
            )
        ],
    )
    classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
    assert frozenset(content.path for content in classfile_digest_contents) == frozenset(
        ["org/pantsbuild/example/lib/ExampleLib.class"]
    )


def test_compile_jdk_versions(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'lib',
                    dependencies = [
                        ':lockfile',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "ExampleLib.java": JAVA_LIB_SOURCE,
        }
    )
    request = CompileJavaSourceRequest(
        targets=CoarsenedTargets([rule_runner.get_target(Address(spec_path="", target_name="lib"))])
    )

    rule_runner.set_options(["--javac-jdk=openjdk:1.16.0-1"])
    assert {
        contents.path
        for contents in rule_runner.request(
            DigestContents, [rule_runner.request(CompiledClassfiles, [request]).digest]
        )
    } == {"org/pantsbuild/example/lib/ExampleLib.class"}

    rule_runner.set_options(["--javac-jdk=adopt:1.8"])
    assert {
        contents.path
        for contents in rule_runner.request(
            DigestContents, [rule_runner.request(CompiledClassfiles, [request]).digest]
        )
    } == {"org/pantsbuild/example/lib/ExampleLib.class"}

    rule_runner.set_options(["--javac-jdk=zulu:1.6"])
    assert {
        contents.path
        for contents in rule_runner.request(
            DigestContents, [rule_runner.request(CompiledClassfiles, [request]).digest]
        )
    } == {"org/pantsbuild/example/lib/ExampleLib.class"}

    rule_runner.set_options(["--javac-jdk=bogusjdk:999"])
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(CompiledClassfiles, [request])


def test_compile_multiple_source_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'lib',
                    dependencies = [
                        ':lockfile',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "ExampleLib.java": JAVA_LIB_SOURCE,
            "OtherLib.java": dedent(
                """\
                package org.pantsbuild.example.lib;

                public class OtherLib {
                    public static String hello() {
                        return "Hello!";
                    }
                }
                """
            ),
        }
    )

    request = CompileJavaSourceRequest(
        targets=rule_runner.request(CoarsenedTargets, [Address(spec_path="", target_name="lib")])
    )
    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
    assert frozenset(content.path for content in classfile_digest_contents) == frozenset(
        ["org/pantsbuild/example/lib/ExampleLib.class", "org/pantsbuild/example/lib/OtherLib.class"]
    )


def test_compile_with_cycle(rule_runner: RuleRunner) -> None:
    """Test that javac can handle source-level cycles--even across build target boundaries--via
    graph coarsening.

    This test has to set up a contrived dependency since build-target cycles are forbidden by the graph.  However,
    file-target cycles are not forbidden, so we configure the graph like so:

    a:a has a single source file, which has file-target address a/A.java, and which inherits a:a's
    explicit dependency on b/B.java.
    b:b depends directly on a:a, and its source b/B.java inherits that dependency.

    Therefore, after target expansion via Get(Targets, Addresses(...)), we get the cycle of:

        a/A.java -> b/B.java -> a/A.java
    """

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "a/BUILD": dedent(
                """\
                java_library(
                    name = 'a',
                    dependencies = [
                        '//:lockfile',
                        'b/B.java',
                    ]
                )
                """
            ),
            "a/A.java": dedent(
                """\
                package org.pantsbuild.a;
                import org.pantsbuild.b.B;
                public interface A {}
                class C implements B {}
                """
            ),
            "b/BUILD": dedent(
                """\
                java_library(
                    name = 'b',
                    dependencies = [
                        '//:lockfile',
                        'a/A.java',
                    ]
                )
                """
            ),
            "b/B.java": dedent(
                """\
                package org.pantsbuild.b;
                import org.pantsbuild.a.A;
                public interface B {};
                class C implements A {}
                """
            ),
        }
    )

    target_a = rule_runner.request(
        Targets, [Addresses([Address(spec_path="a", target_name="a")])]
    ).expect_single()
    component = rule_runner.request(CoarsenedTargets, [target_a.address])
    assert sorted([t.address.spec for t in component]) == ["a/A.java", "b/B.java"]
    compiled_classfiles = rule_runner.request(
        CompiledClassfiles, [CompileJavaSourceRequest(targets=component)]
    )
    classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
    assert frozenset(content.path for content in classfile_digest_contents) == frozenset(
        [
            "org/pantsbuild/a/A.class",
            "org/pantsbuild/a/C.class",
            "org/pantsbuild/b/B.class",
            "org/pantsbuild/b/C.class",
        ]
    )


def test_compile_with_transitive_cycle(rule_runner: RuleRunner) -> None:
    """Like test_compile_with_cycle, but the input isn't pre-coarsened by the test."""

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'main',
                    dependencies = [
                        '//:lockfile',
                        'a:a',
                    ]
                )
                """
            ),
            "Main.java": dedent(
                """\
                package org.pantsbuild.main;
                import org.pantsbuild.a.A;
                public class Main implements A {}
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "a/BUILD": dedent(
                """\
                java_library(
                    name = 'a',
                    dependencies = [
                        '//:lockfile',
                        'b/B.java',
                    ]
                )
                """
            ),
            "a/A.java": dedent(
                """\
                package org.pantsbuild.a;
                import org.pantsbuild.b.B;
                public interface A {}
                class C implements B {}
                """
            ),
            "b/BUILD": dedent(
                """\
                java_library(
                    name = 'b',
                    dependencies = [
                        '//:lockfile',
                        'a:a',
                    ]
                )
                """
            ),
            "b/B.java": dedent(
                """\
                package org.pantsbuild.b;
                import org.pantsbuild.a.A;
                public interface B {};
                class C implements A {}
                """
            ),
        }
    )

    target_main = rule_runner.request(
        Targets, [Addresses([Address(spec_path="", target_name="main")])]
    ).expect_single()
    component = rule_runner.request(CoarsenedTargets, [target_main.address])
    assert [t.address.spec for t in component] == ["//Main.java:main"]
    compiled_classfiles = rule_runner.request(
        CompiledClassfiles, [CompileJavaSourceRequest(targets=component)]
    )
    classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
    assert frozenset(content.path for content in classfile_digest_contents) == frozenset(
        ["org/pantsbuild/main/Main.class"]
    )


def test_compile_with_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'main',
                    dependencies = [
                        ':lockfile',
                        'lib:lib',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "Example.java": JAVA_LIB_MAIN_SOURCE,
            "lib/BUILD": dedent(
                """\
                java_library(
                    name = 'lib',
                    dependencies = [
                        '//:lockfile',
                    ]
                )
                """
            ),
            "lib/ExampleLib.java": JAVA_LIB_SOURCE,
        }
    )

    request = CompileJavaSourceRequest(
        targets=rule_runner.request(CoarsenedTargets, [Address(spec_path="", target_name="main")])
    )
    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
    assert len(classfile_digest_contents) == 1
    assert classfile_digest_contents[0].path == "org/pantsbuild/example/Example.class"


def test_compile_with_missing_dep_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'main',
                    dependencies = [
                        ':lockfile',
                    ]
                )
                """
            ),
            "Example.java": JAVA_LIB_MAIN_SOURCE,
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
        }
    )

    request = CompileJavaSourceRequest(
        targets=rule_runner.request(CoarsenedTargets, [Address(spec_path="", target_name="main")])
    )
    expected_exception_msg = r".*?package org.pantsbuild.example.lib does not exist.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(CompiledClassfiles, [request])


def test_compile_with_maven_deps(rule_runner: RuleRunner) -> None:
    resolved_joda_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=MavenCoord(coord="joda-time:joda-time:2.10.10"),
                file_name="joda-time-2.10.10.jar",
                direct_dependencies=MavenCoordinates([]),
                dependencies=MavenCoordinates([]),
                file_digest=FileDigest(
                    fingerprint="dd8e7c92185a678d1b7b933f31209b6203c8ffa91e9880475a1be0346b9617e3",
                    serialized_bytes_length=644419,
                ),
            ),
        )
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = ["joda-time:joda-time:2.10.10"],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'main',
                    dependencies = [
                        ':lockfile',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": resolved_joda_lockfile.to_json().decode("utf-8"),
            "Example.java": dedent(
                """
                package org.pantsbuild.example;

                import org.joda.time.DateTime;

                public class Example {
                    public static void main(String[] args) {
                        DateTime dt = new DateTime();
                        System.out.println(dt.getYear());
                    }
                }
                """
            ),
        }
    )
    request = CompileJavaSourceRequest(
        targets=rule_runner.request(CoarsenedTargets, [Address(spec_path="", target_name="main")])
    )
    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
    assert len(classfile_digest_contents) == 1
    assert classfile_digest_contents[0].path == "org/pantsbuild/example/Example.class"


def test_compile_with_missing_maven_dep_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                coursier_lockfile(
                    name = 'lockfile',
                    maven_requirements = [],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )

                java_library(
                    name = 'main',
                    dependencies = [
                        ':lockfile',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "Example.java": dedent(
                """
                package org.pantsbuild.example;

                import org.joda.time.DateTime;

                public class Example {
                    public static void main(String[] args) {
                        DateTime dt = new DateTime();
                        System.out.println(dt.getYear());
                    }
                }
                """
            ),
        }
    )

    request = CompileJavaSourceRequest(
        targets=rule_runner.request(CoarsenedTargets, [Address(spec_path="", target_name="main")])
    )
    expected_exception_msg = r".*?package org.joda.time does not exist.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(CompiledClassfiles, [request])
