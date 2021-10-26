# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import CompileJavaSourceRequest, JavacCheckRequest
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference import java_parser, java_parser_launcher
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.util_rules import archive, config_files, source_files
from pants.core.util_rules.archive import UnzipBinary
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, FileDigest, RemovePrefix, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, Targets
from pants.jvm import jdk_rules
from pants.jvm.compile import CompiledClassfiles, CompileResult, FallibleCompiledClassfiles
from pants.jvm.goals.coursier import rules as coursier_rules
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, logging

NAMED_RESOLVE_OPTIONS = '--jvm-resolves={"test": "coursier_resolve.lockfile"}'
DEFAULT_RESOLVE_OPTION = "--jvm-default-resolve=test"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            render_classpath,
            QueryRule(RenderedClasspath, (Digest,)),
            *archive.rules(),
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *javac_rules(),
            *util_rules(),
            *target_types_rules(),
            *coursier_rules(),
            *jdk_rules.rules(),
            *java_dep_inf_rules(),
            *java_parser.rules(),
            *java_parser_launcher.rules(),
            *source_files.rules(),
            QueryRule(CheckResults, (JavacCheckRequest,)),
            QueryRule(FallibleCompiledClassfiles, (CompileJavaSourceRequest,)),
            QueryRule(CompiledClassfiles, (CompileJavaSourceRequest,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[JvmDependencyLockfile, JavaSourcesGeneratorTarget, JvmArtifact],
        bootstrap_args=[
            NAMED_RESOLVE_OPTIONS,
            DEFAULT_RESOLVE_OPTION,
        ],
    )
    rule_runner.set_options(
        args=[NAMED_RESOLVE_OPTIONS, DEFAULT_RESOLVE_OPTION], env_inherit=PYTHON_BOOTSTRAP_ENV
    )
    return rule_runner


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


@dataclass(frozen=True)
class RenderedClasspath:
    """The contents of a classpath, organized as a key per entry with its contained classfiles."""

    content: dict[str, set[str]]


@rule
async def render_classpath(snapshot: Snapshot, unzip_binary: UnzipBinary) -> RenderedClasspath:
    dest_dir = "dest"
    process_results = await MultiGet(
        Get(
            ProcessResult,
            Process(
                argv=[
                    unzip_binary.path,
                    "-d",
                    dest_dir,
                    filename,
                ],
                input_digest=snapshot.digest,
                output_directories=(dest_dir,),
                description=f"Extract {filename}",
            ),
        )
        for filename in snapshot.files
    )

    listing_snapshots = await MultiGet(
        Get(Snapshot, RemovePrefix(pr.output_digest, dest_dir)) for pr in process_results
    )

    return RenderedClasspath(
        {path: set(listing.files) for path, listing in zip(snapshot.files, listing_snapshots)}
    )


def expect_single_expanded_coarsened_target(
    rule_runner: RuleRunner, address: Address
) -> CoarsenedTarget:
    expanded_target = rule_runner.request(Targets, [Addresses([address])]).expect_single()
    coarsened_targets = rule_runner.request(
        CoarsenedTargets, [Addresses([expanded_target.address])]
    )
    assert len(coarsened_targets) == 1
    return coarsened_targets[0]


@maybe_skip_jdk_test
def test_compile_no_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'lib',

                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "ExampleLib.java": JAVA_LIB_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [CompileJavaSourceRequest(component=coarsened_target)],
    )

    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".ExampleLib.java.lib.jar": {"org/pantsbuild/example/lib/ExampleLib.class"}
    }

    # Additionally validate that `check` works.
    check_results = rule_runner.request(
        CheckResults,
        [
            JavacCheckRequest(
                [JavacCheckRequest.field_set_type.create(coarsened_target.representative)]
            )
        ],
    )

    assert len(check_results.results) == 1
    check_result = check_results.results[0]
    assert check_result.partition_description == str(coarsened_target)


@maybe_skip_jdk_test
def test_compile_jdk_versions(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'lib',

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
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="lib")
        )
    )
    rule_runner.set_options(
        ["--javac-jdk=zulu:8.0.312", NAMED_RESOLVE_OPTIONS, DEFAULT_RESOLVE_OPTION],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".ExampleLib.java.lib.jar": {"org/pantsbuild/example/lib/ExampleLib.class"}
    }

    rule_runner.set_options(
        ["--javac-jdk=bogusjdk:999", NAMED_RESOLVE_OPTIONS, DEFAULT_RESOLVE_OPTION],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(CompiledClassfiles, [request])


@maybe_skip_jdk_test
def test_compile_multiple_source_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'lib',

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

    expanded_targets = rule_runner.request(
        Targets, [Addresses([Address(spec_path="", target_name="lib")])]
    )
    assert sorted(t.address.spec for t in expanded_targets) == [
        "//ExampleLib.java:lib",
        "//OtherLib.java:lib",
    ]

    coarsened_targets = rule_runner.request(
        CoarsenedTargets, [Addresses([t.address for t in expanded_targets])]
    )
    assert len(coarsened_targets) == 2
    assert all(len(ctgt.members) == 1 for ctgt in coarsened_targets)

    coarsened_targets_sorted = sorted(
        list(coarsened_targets), key=lambda ctgt: str(list(ctgt.members)[0].address)
    )

    request0 = CompileJavaSourceRequest(component=coarsened_targets_sorted[0])
    compiled_classfiles0 = rule_runner.request(CompiledClassfiles, [request0])
    classpath0 = rule_runner.request(RenderedClasspath, [compiled_classfiles0.digest])
    assert classpath0.content == {
        ".ExampleLib.java.lib.jar": {
            "org/pantsbuild/example/lib/ExampleLib.class",
        }
    }

    request1 = CompileJavaSourceRequest(component=coarsened_targets_sorted[1])
    compiled_classfiles1 = rule_runner.request(CompiledClassfiles, [request1])
    classpath1 = rule_runner.request(RenderedClasspath, [compiled_classfiles1.digest])
    assert classpath1.content == {
        ".OtherLib.java.lib.jar": {
            "org/pantsbuild/example/lib/OtherLib.class",
        }
    }


@maybe_skip_jdk_test
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
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "a/BUILD": dedent(
                """\
                java_sources(
                    name = 'a',

                    dependencies = [
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
                java_sources(
                    name = 'b',

                    dependencies = [
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
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="a", target_name="a")
    )
    assert sorted(t.address.spec for t in coarsened_target.members) == ["a/A.java", "b/B.java"]
    request = CompileJavaSourceRequest(component=coarsened_target)

    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        "a.A.java.jar": {
            "org/pantsbuild/a/A.class",
            "org/pantsbuild/a/C.class",
            "org/pantsbuild/b/B.class",
            "org/pantsbuild/b/C.class",
        }
    }


@maybe_skip_jdk_test
def test_compile_with_transitive_cycle(rule_runner: RuleRunner) -> None:
    """Like test_compile_with_cycle, but the cycle occurs as a transitive dep of the requested
    target."""

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'main',

                    dependencies = [
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
                java_sources(
                    name = 'a',

                    dependencies = [
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
                java_sources(
                    name = 'b',

                    dependencies = [
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

    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [
            CompileJavaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                )
            )
        ],
    )
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {".Main.java.main.jar": {"org/pantsbuild/main/Main.class"}}


@logging
@maybe_skip_jdk_test
def test_compile_with_transitive_multiple_sources(rule_runner: RuleRunner) -> None:
    """Like test_compile_with_transitive_cycle, but the cycle occurs via subtarget source expansion
    rather than explicitly."""

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'main',

                    dependencies = [
                        'lib:lib',
                    ]
                )
                """
            ),
            "Main.java": dedent(
                """\
                package org.pantsbuild.main;
                import org.pantsbuild.a.A;
                import org.pantsbuild.b.B;
                public class Main implements A {}
                class Other implements B {}
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "lib/BUILD": dedent(
                """\
                java_sources(
                    name = 'lib',

                )
                """
            ),
            "lib/A.java": dedent(
                """\
                package org.pantsbuild.a;
                import org.pantsbuild.b.B;
                public interface A {}
                class C implements B {}
                """
            ),
            "lib/B.java": dedent(
                """\
                package org.pantsbuild.b;
                import org.pantsbuild.a.A;
                public interface B {};
                class C implements A {}
                """
            ),
        }
    )

    ctgt = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="main")
    )

    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [CompileJavaSourceRequest(component=ctgt)],
    )
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".Main.java.main.jar": {"org/pantsbuild/main/Main.class", "org/pantsbuild/main/Other.class"}
    }


@maybe_skip_jdk_test
def test_compile_with_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'main',

                    dependencies = [
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
                java_sources(
                    name = 'lib',

                )
                """
            ),
            "lib/ExampleLib.java": JAVA_LIB_SOURCE,
        }
    )
    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [
            CompileJavaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                )
            )
        ],
    )
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {".Example.java.main.jar": {"org/pantsbuild/example/Example.class"}}


@maybe_skip_jdk_test
def test_compile_of_package_info(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'main',

                )
                """
            ),
            "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
            .to_json()
            .decode("utf-8"),
            "package-info.java": dedent(
                """
                package org.pantsbuild.example;
                /**
                  * This is a package-info.java file which can have package-level annotations and
                  * documentation comments. It does not generate any output.
                  */
                """
            ),
        }
    )
    compiled_classfiles = rule_runner.request(
        CompiledClassfiles,
        [
            CompileJavaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                )
            )
        ],
    )
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {}


@maybe_skip_jdk_test
def test_compile_with_missing_dep_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'main',

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
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        )
    )
    fallible_result = rule_runner.request(FallibleCompiledClassfiles, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "package org.pantsbuild.example.lib does not exist" in fallible_result.stderr


@maybe_skip_jdk_test
def test_compile_with_maven_deps(rule_runner: RuleRunner) -> None:
    resolved_joda_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(group="joda-time", artifact="joda-time", version="2.10.10"),
                file_name="joda-time-2.10.10.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
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
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )

                java_sources(
                    name = 'main',

                    dependencies = [
                        ':joda-time_joda-time',
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
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        )
    )
    compiled_classfiles = rule_runner.request(CompiledClassfiles, [request])
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {".Example.java.main.jar": {"org/pantsbuild/example/Example.class"}}


@maybe_skip_jdk_test
def test_compile_with_missing_maven_dep_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'main',

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
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        )
    )
    fallible_result = rule_runner.request(FallibleCompiledClassfiles, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "package org.joda.time does not exist" in fallible_result.stderr
