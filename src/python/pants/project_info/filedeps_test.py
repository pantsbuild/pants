# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Set
from unittest import skip

from pants.backend.codegen.thrift.java.java_thrift_library import (
    JavaThriftLibrary as JavaThriftLibraryV1,
)
from pants.backend.jvm.targets.java_library import JavaLibrary as JavaLibraryV1
from pants.backend.jvm.targets.jvm_app import JvmApp as JvmAppV1
from pants.backend.jvm.targets.jvm_binary import JvmBinary as JvmBinaryV1
from pants.backend.jvm.targets.scala_library import ScalaLibrary as ScalaLibraryV1
from pants.backend.python.target_types import PythonLibrary
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources as ResourcesV1
from pants.build_graph.target import Target as TargetV1
from pants.core.target_types import GenericTarget, Resources
from pants.project_info import filedeps
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class FileDepsTest(GoalRuleTestBase):

    goal_cls = filedeps.Filedeps

    @classmethod
    def rules(cls):
        return (*super().rules(), *filedeps.rules())

    @classmethod
    def target_types(cls):
        return [GenericTarget, Resources, PythonLibrary]

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(
            targets={
                "target": TargetV1,
                "resources": ResourcesV1,
                "java_library": JavaLibraryV1,
                "java_thrift_library": JavaThriftLibraryV1,
                "jvm_app": JvmAppV1,
                "jvm_binary": JvmBinaryV1,
                "scala_library": ScalaLibraryV1,
                "python_library": PythonLibraryV1,
            },
        )

    def create_python_library(
        self,
        path: str,
        *,
        sources: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None
    ) -> None:
        self.create_library(
            path=path,
            target_type="python_library",
            name="target",
            sources=sources or [],
            dependencies=dependencies or [],
        )

    def assert_filedeps(
        self,
        *,
        targets: List[str],
        expected: Set[str],
        transitive: bool = False,
        globs: bool = False
    ) -> None:
        args = ["--no-filedeps2-absolute"]
        if globs:
            args.append("--filedeps2-globs")
        if transitive:
            args.append("--filedeps2-transitive")
        self.assert_console_output(*expected, args=(*args, *targets))

    def test_no_target(self) -> None:
        self.assert_filedeps(targets=[], expected=set())

    def test_one_target_no_source(self) -> None:
        self.add_to_build_file("some/target", target="target()")
        self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD"})

    def test_one_target_one_source(self) -> None:
        self.create_python_library("some/target", sources=["file.py"])
        self.assert_filedeps(
            targets=["some/target"], expected={"some/target/BUILD", "some/target/file.py"}
        )

    def test_one_target_multiple_source(self) -> None:
        self.create_python_library("some/target", sources=["file1.py", "file2.py"])
        self.assert_filedeps(
            targets=["some/target"],
            expected={"some/target/BUILD", "some/target/file1.py", "some/target/file2.py"},
        )

    def test_one_target_no_source_one_dep(self) -> None:
        self.create_python_library("dep/target", sources=["file.py"])
        self.create_python_library("some/target", dependencies=["dep/target"])
        self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD"})
        self.assert_filedeps(
            targets=["some/target"],
            transitive=True,
            expected={"some/target/BUILD", "dep/target/BUILD", "dep/target/file.py"},
        )

    def test_one_target_one_source_with_dep(self) -> None:
        self.create_python_library("dep/target", sources=["file.py"])
        self.create_python_library("some/target", sources=["file.py"], dependencies=["dep/target"])
        direct_files = {"some/target/BUILD", "some/target/file.py"}
        self.assert_filedeps(
            targets=["some/target"], expected=direct_files,
        )
        self.assert_filedeps(
            targets=["some/target"],
            transitive=True,
            expected={*direct_files, "dep/target/BUILD", "dep/target/file.py",},
        )

    def test_multiple_targets_one_source(self) -> None:
        self.create_python_library("some/target", sources=["file.py"])
        self.create_python_library("other/target", sources=["file.py"])
        self.assert_filedeps(
            targets=["some/target", "other/target"],
            expected={
                "some/target/BUILD",
                "some/target/file.py",
                "other/target/BUILD",
                "other/target/file.py",
            },
        )

    def test_multiple_targets_one_source_with_dep(self) -> None:
        self.create_python_library("dep1/target", sources=["file.py"])
        self.create_python_library("dep2/target", sources=["file.py"])
        self.create_python_library("some/target", sources=["file.py"], dependencies=["dep1/target"])
        self.create_python_library(
            "other/target", sources=["file.py"], dependencies=["dep2/target"]
        )
        direct_files = {
            "some/target/BUILD",
            "some/target/file.py",
            "other/target/BUILD",
            "other/target/file.py",
        }
        self.assert_filedeps(
            targets=["some/target", "other/target"], expected=direct_files,
        )
        self.assert_filedeps(
            targets=["some/target", "other/target"],
            transitive=True,
            expected={
                *direct_files,
                "dep1/target/BUILD",
                "dep1/target/file.py",
                "dep2/target/BUILD",
                "dep2/target/file.py",
            },
        )

    def test_multiple_targets_one_source_overlapping(self) -> None:
        self.create_python_library("dep/target", sources=["file.py"])
        self.create_python_library("some/target", sources=["file.py"], dependencies=["dep/target"])
        self.create_python_library("other/target", sources=["file.py"], dependencies=["dep/target"])
        direct_files = {
            "some/target/BUILD",
            "some/target/file.py",
            "other/target/BUILD",
            "other/target/file.py",
        }
        self.assert_filedeps(targets=["some/target", "other/target"], expected=direct_files)
        self.assert_filedeps(
            targets=["some/target", "other/target"],
            transitive=True,
            expected={*direct_files, "dep/target/BUILD", "dep/target/file.py"},
        )

    def test_globs(self) -> None:
        self.create_files("some/target", ["test1.py", "test2.py"])
        self.add_to_build_file("some/target", target="target(name='target', sources=['test*.py'])")
        self.assert_filedeps(
            targets=["some/target"],
            expected={"some/target/BUILD", "some/target/test*.py"},
            globs=True,
        )

    def test_build_with_file_ext(self) -> None:
        self.create_file("some/target/BUILD.ext", contents="target()")
        self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD.ext"})

    def test_resources(self) -> None:
        self.create_resources("src/resources", "data", "data.json")
        self.assert_filedeps(
            targets=["src/resources:data"],
            expected={"src/resources/BUILD", "src/resources/data.json"},
        )

    @skip(
        "V2 does not yet hydrate java_sources for scala_library targets. Once this happens, "
        "we must teach filedeps.py to check the target_adaptor for java_sources."
    )
    def test_scala_with_java_sources(self) -> None:
        self.create_file("src/java/j.java")
        self.create_file("src/scala/s.scala")
        self.add_to_build_file(
            "src/java", target="java_library(sources=['j.java'], dependencies=['src/scala'])"
        )
        self.add_to_build_file(
            "src/scala", target="scala_library(sources=['s.scala'], java_sources=['src/java'])"
        )
        expected = {"src/java/BUILD", "src/java/j.java", "src/scala/BUILD", "src/scala/s.scala"}
        self.assert_filedeps(targets=["src/java"], expected=expected)
        self.assert_filedeps(targets=["src/scala"], expected=expected)

    @skip("Unskip once we have codegen bindings.")
    def test_filter_out_synthetic_targets(self) -> None:
        self.create_library(
            path="src/thrift/storage",
            target_type="java_thrift_library",
            name="storage",
            sources=["data_types.thrift"],
        )
        java_lib = self.create_library(
            path="src/java/lib",
            target_type="java_library",
            name="lib",
            sources=["lib1.java"],
            dependencies=["src/thrift/storage"],
        )
        self.create_file(".pants.d/gen/thrift/java/storage/Angle.java")
        synthetic_java_lib = self.make_target(
            spec=".pants.d/gen/thrift/java/storage",
            target_type=JavaLibraryV1,
            derived_from=self.target("src/thrift/storage"),
            sources=["Angle.java"],
        )
        java_lib.inject_dependency(synthetic_java_lib.address)
        self.assert_filedeps(
            targets=["src/java/lib"],
            expected={
                "src/java/lib/BUILD",
                "src/java/lib/lib1.java",
                "src/thrift/storage/BUILD",
                "src/thrift/storage/data_types.thrift",
            },
        )

    @skip(
        "V2 does not yet hydrate bundles or binary attributes for jvm_app. After this is added,"
        "we must add similar logic to the V1 filedeps goal for jvm_apps."
    )
    def test_jvm_app(self) -> None:
        self.create_library(
            path="src/thrift/storage",
            target_type="java_thrift_library",
            name="storage",
            sources=["data_types.thrift"],
        )
        self.create_library(
            path="src/java/lib",
            target_type="java_library",
            name="lib",
            sources=["lib1.java"],
            dependencies=["src/thrift/storage"],
        )
        self.create_library(
            path="src/java/bin",
            target_type="jvm_binary",
            name="bin",
            sources=["main.java"],
            dependencies=["src/java/lib"],
        )
        self.create_file("project/config/app.yaml")
        self.create_library(
            path="project", target_type="jvm_app", name="app",
        )
        self.assert_filedeps(
            targets=["project:app"],
            expected={
                "project/BUILD",
                "project/config/app.yaml",
                "src/java/bin/BUILD",
                "src/java/bin/main.java",
                "src/java/lib/BUILD",
                "src/java/lib/lib1.java",
                "src/thrift/storage/BUILD" "src/thrift/storage/data_types.thrift",
            },
        )
