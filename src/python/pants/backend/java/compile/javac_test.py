# # Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# # Licensed under the Apache License, Version 2.0 (see LICENSE).

# from __future__ import annotations

# from textwrap import dedent

# import pytest

# from pants.backend.java.compile.javac import CompiledClassfiles, CompileJavaSourceRequest
# from pants.backend.java.compile.javac import rules as javac_rules
# from pants.backend.java.compile.javac_binary import rules as javac_binary_rules
# from pants.backend.java.target_types import JavaLibrary
# from pants.build_graph.address import Address
# from pants.core.util_rules import config_files, source_files
# from pants.core.util_rules.external_tool import rules as external_tool_rules
# from pants.engine.fs import DigestContents, FileDigest
# from pants.engine.internals.scheduler import ExecutionError
# from pants.jvm.resolve.coursier_fetch import (
#     CoursierLockfileEntry,
#     CoursierResolvedLockfile,
#     MavenCoord,
#     MavenCoordinates,
# )
# from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
# from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
# from pants.jvm.target_types import JvmDependencyLockfile
# from pants.jvm.util_rules import rules as util_rules
# from pants.testutil.rule_runner import QueryRule, RuleRunner


# @pytest.fixture
# def rule_runner() -> RuleRunner:
#     return RuleRunner(
#         rules=[
#             *config_files.rules(),
#             *coursier_fetch_rules(),
#             *coursier_setup_rules(),
#             *external_tool_rules(),
#             *source_files.rules(),
#             *javac_rules(),
#             *util_rules(),
#             *javac_binary_rules(),
#             QueryRule(CompiledClassfiles, (CompileJavaSourceRequest,)),
#         ],
#         target_types=[JvmDependencyLockfile, JavaLibrary],
#     )


# JAVA_LIB_SOURCE = dedent(
#     """
#     package org.pantsbuild.example.lib;

#     public class ExampleLib {
#         public static String hello() {
#             return "Hello!";
#         }
#     }
#     """
# )

# JAVA_LIB_MAIN_SOURCE = dedent(
#     """
#     package org.pantsbuild.example;

#     import org.pantsbuild.example.lib.ExampleLib;

#     public class Example {
#         public static void main(String[] args) {
#             System.out.println(ExampleLib.hello());
#         }
#     }
#     """
# )


# def test_compile_no_deps(rule_runner: RuleRunner) -> None:
#     rule_runner.write_files(
#         {
#             "BUILD": dedent(
#                 """\
#                 coursier_lockfile(
#                     name = 'lockfile',
#                     maven_requirements = [],
#                     sources = [
#                         "coursier_resolve.lockfile",
#                     ],
#                 )

#                 java_library(
#                     name = 'lib',
#                     dependencies = [
#                         ':lockfile',
#                     ]
#                 )
#                 """
#             ),
#             "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
#             .to_json()
#             .decode("utf-8"),
#             "ExampleLib.java": JAVA_LIB_SOURCE,
#         }
#     )

#     compiled_classfiles = rule_runner.request(
#         CompiledClassfiles,
#         [
#             CompileJavaSourceRequest(
#                 target=rule_runner.get_target(address=Address(spec_path="", target_name="lib"))
#             )
#         ],
#     )
#     classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
#     assert len(classfile_digest_contents) == 1
#     assert classfile_digest_contents[0].path == "org/pantsbuild/example/lib/ExampleLib.class"


# def test_compile_jdk_versions(rule_runner: RuleRunner) -> None:
#     rule_runner.write_files(
#         {
#             "BUILD": dedent(
#                 """\
#                 coursier_lockfile(
#                     name = 'lockfile',
#                     maven_requirements = [],
#                     sources = [
#                         "coursier_resolve.lockfile",
#                     ],
#                 )

#                 java_library(
#                     name = 'lib',
#                     dependencies = [
#                         ':lockfile',
#                     ]
#                 )
#                 """
#             ),
#             "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
#             .to_json()
#             .decode("utf-8"),
#             "ExampleLib.java": JAVA_LIB_SOURCE,
#         }
#     )
#     request = CompileJavaSourceRequest(
#         target=rule_runner.get_target(address=Address(spec_path="", target_name="lib"))
#     )

#     rule_runner.set_options(["--javac-jdk=openjdk:1.16.0-1"])
#     assert {
#         contents.path
#         for contents in rule_runner.request(
#             DigestContents, [rule_runner.request(CompiledClassfiles, [request]).digest]
#         )
#     } == {"org/pantsbuild/example/lib/ExampleLib.class"}

#     rule_runner.set_options(["--javac-jdk=adopt:1.8"])
#     assert {
#         contents.path
#         for contents in rule_runner.request(
#             DigestContents, [rule_runner.request(CompiledClassfiles, [request]).digest]
#         )
#     } == {"org/pantsbuild/example/lib/ExampleLib.class"}

#     rule_runner.set_options(["--javac-jdk=zulu:1.6"])
#     assert {
#         contents.path
#         for contents in rule_runner.request(
#             DigestContents, [rule_runner.request(CompiledClassfiles, [request]).digest]
#         )
#     } == {"org/pantsbuild/example/lib/ExampleLib.class"}

#     rule_runner.set_options(["--javac-jdk=bogusjdk:999"])
#     expected_exception_msg = r".*?JVM bogusjdk:999 not found in index.*?"
#     with pytest.raises(ExecutionError, match=expected_exception_msg):
#         rule_runner.request(CompiledClassfiles, [request])


# def test_compile_with_deps(rule_runner: RuleRunner) -> None:
#     rule_runner.write_files(
#         {
#             "BUILD": dedent(
#                 """\
#                 coursier_lockfile(
#                     name = 'lockfile',
#                     maven_requirements = [],
#                     sources = [
#                         "coursier_resolve.lockfile",
#                     ],
#                 )

#                 java_library(
#                     name = 'main',
#                     dependencies = [
#                         ':lockfile',
#                         'lib:lib',
#                     ]
#                 )
#                 """
#             ),
#             "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
#             .to_json()
#             .decode("utf-8"),
#             "Example.java": JAVA_LIB_MAIN_SOURCE,
#             "lib/BUILD": dedent(
#                 """\
#                 java_library(
#                     name = 'lib',
#                     dependencies = [
#                         '//:lockfile',
#                     ]
#                 )
#                 """
#             ),
#             "lib/ExampleLib.java": JAVA_LIB_SOURCE,
#         }
#     )

#     compiled_classfiles = rule_runner.request(
#         CompiledClassfiles,
#         [
#             CompileJavaSourceRequest(
#                 target=rule_runner.get_target(address=Address(spec_path="", target_name="main"))
#             )
#         ],
#     )
#     classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
#     assert len(classfile_digest_contents) == 1
#     assert classfile_digest_contents[0].path == "org/pantsbuild/example/Example.class"


# def test_compile_with_missing_dep_fails(rule_runner: RuleRunner) -> None:
#     rule_runner.write_files(
#         {
#             "BUILD": dedent(
#                 """\
#                 coursier_lockfile(
#                     name = 'lockfile',
#                     maven_requirements = [],
#                     sources = [
#                         "coursier_resolve.lockfile",
#                     ],
#                 )

#                 java_library(
#                     name = 'main',
#                     dependencies = [
#                         ':lockfile',
#                     ]
#                 )
#                 """
#             ),
#             "Example.java": JAVA_LIB_MAIN_SOURCE,
#             "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
#             .to_json()
#             .decode("utf-8"),
#         }
#     )

#     compile_request = CompileJavaSourceRequest(
#         target=rule_runner.get_target(address=Address(spec_path="", target_name="main"))
#     )
#     expected_exception_msg = r".*?package org.pantsbuild.example.lib does not exist.*?"
#     with pytest.raises(ExecutionError, match=expected_exception_msg):
#         rule_runner.request(CompiledClassfiles, [compile_request])


# def test_compile_with_maven_deps(rule_runner: RuleRunner) -> None:
#     resolved_joda_lockfile = CoursierResolvedLockfile(
#         entries=(
#             CoursierLockfileEntry(
#                 coord=MavenCoord(coord="joda-time:joda-time:2.10.10"),
#                 file_name="joda-time-2.10.10.jar",
#                 direct_dependencies=MavenCoordinates([]),
#                 dependencies=MavenCoordinates([]),
#                 file_digest=FileDigest(
#                     fingerprint="dd8e7c92185a678d1b7b933f31209b6203c8ffa91e9880475a1be0346b9617e3",
#                     serialized_bytes_length=644419,
#                 ),
#             ),
#         )
#     )
#     rule_runner.write_files(
#         {
#             "BUILD": dedent(
#                 """\
#                 coursier_lockfile(
#                     name = 'lockfile',
#                     maven_requirements = ["joda-time:joda-time:2.10.10"],
#                     sources = [
#                         "coursier_resolve.lockfile",
#                     ],
#                 )

#                 java_library(
#                     name = 'main',
#                     dependencies = [
#                         ':lockfile',
#                     ]
#                 )
#                 """
#             ),
#             "coursier_resolve.lockfile": resolved_joda_lockfile.to_json().decode("utf-8"),
#             "Example.java": dedent(
#                 """
#                 package org.pantsbuild.example;

#                 import org.joda.time.DateTime;

#                 public class Example {
#                     public static void main(String[] args) {
#                         DateTime dt = new DateTime();
#                         System.out.println(dt.getYear());
#                     }
#                 }
#                 """
#             ),
#         }
#     )

#     compiled_classfiles = rule_runner.request(
#         CompiledClassfiles,
#         [
#             CompileJavaSourceRequest(
#                 target=rule_runner.get_target(address=Address(spec_path="", target_name="main"))
#             )
#         ],
#     )
#     classfile_digest_contents = rule_runner.request(DigestContents, [compiled_classfiles.digest])
#     assert len(classfile_digest_contents) == 1
#     assert classfile_digest_contents[0].path == "org/pantsbuild/example/Example.class"


# def test_compile_with_missing_maven_dep_fails(rule_runner: RuleRunner) -> None:
#     rule_runner.write_files(
#         {
#             "BUILD": dedent(
#                 """\
#                 coursier_lockfile(
#                     name = 'lockfile',
#                     maven_requirements = [],
#                     sources = [
#                         "coursier_resolve.lockfile",
#                     ],
#                 )

#                 java_library(
#                     name = 'main',
#                     dependencies = [
#                         ':lockfile',
#                     ]
#                 )
#                 """
#             ),
#             "coursier_resolve.lockfile": CoursierResolvedLockfile(entries=())
#             .to_json()
#             .decode("utf-8"),
#             "Example.java": dedent(
#                 """
#                 package org.pantsbuild.example;

#                 import org.joda.time.DateTime;

#                 public class Example {
#                     public static void main(String[] args) {
#                         DateTime dt = new DateTime();
#                         System.out.println(dt.getYear());
#                     }
#                 }
#                 """
#             ),
#         }
#     )

#     compile_request = CompileJavaSourceRequest(
#         target=rule_runner.get_target(address=Address(spec_path="", target_name="main"))
#     )
#     expected_exception_msg = r".*?package org.joda.time does not exist.*?"
#     with pytest.raises(ExecutionError, match=expected_exception_msg):
#         rule_runner.request(CompiledClassfiles, [compile_request])
