# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Set
from unittest import skip

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.project_info import filedeps
from pants.engine.target import Dependencies, Sources, Target
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Sources, Dependencies)


class FiledepsTest(GoalRuleTestBase):
    goal_cls = filedeps.Filedeps

    @classmethod
    def rules(cls):
        return (*super().rules(), *filedeps.rules())

    @classmethod
    def target_types(cls):
        return [MockTarget, ProtobufLibrary]

    def setup_target(
        self,
        path: str,
        *,
        sources: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
    ) -> None:
        if sources:
            self.create_files(path, sources)
        self.add_to_build_file(
            path, f"tgt(sources={sources or []}, dependencies={dependencies or []})",
        )

    def assert_filedeps(
        self,
        *,
        targets: List[str],
        expected: Set[str],
        transitive: bool = False,
        globs: bool = False,
    ) -> None:
        args = []
        if globs:
            args.append("--filedeps2-globs")
        if transitive:
            args.append("--filedeps2-transitive")
        self.assert_console_output(*expected, args=(*args, *targets))

    def test_no_target(self) -> None:
        self.assert_filedeps(targets=[], expected=set())

    def test_one_target_no_source(self) -> None:
        self.setup_target("some/target")
        self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD"})

    def test_one_target_one_source(self) -> None:
        self.setup_target("some/target", sources=["file.py"])
        self.assert_filedeps(
            targets=["some/target"], expected={"some/target/BUILD", "some/target/file.py"}
        )

    def test_one_target_multiple_source(self) -> None:
        self.setup_target("some/target", sources=["file1.py", "file2.py"])
        self.assert_filedeps(
            targets=["some/target"],
            expected={"some/target/BUILD", "some/target/file1.py", "some/target/file2.py"},
        )

    def test_one_target_no_source_one_dep(self) -> None:
        self.setup_target("dep/target", sources=["file.py"])
        self.setup_target("some/target", dependencies=["dep/target"])
        self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD"})
        self.assert_filedeps(
            targets=["some/target"],
            transitive=True,
            expected={"some/target/BUILD", "dep/target/BUILD", "dep/target/file.py"},
        )

    def test_one_target_one_source_with_dep(self) -> None:
        self.setup_target("dep/target", sources=["file.py"])
        self.setup_target("some/target", sources=["file.py"], dependencies=["dep/target"])
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
        self.setup_target("some/target", sources=["file.py"])
        self.setup_target("other/target", sources=["file.py"])
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
        self.setup_target("dep1/target", sources=["file.py"])
        self.setup_target("dep2/target", sources=["file.py"])
        self.setup_target("some/target", sources=["file.py"], dependencies=["dep1/target"])
        self.setup_target("other/target", sources=["file.py"], dependencies=["dep2/target"])
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
        self.setup_target("dep/target", sources=["file.py"])
        self.setup_target("some/target", sources=["file.py"], dependencies=["dep/target"])
        self.setup_target("other/target", sources=["file.py"], dependencies=["dep/target"])
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
        self.add_to_build_file("some/target", target="tgt(sources=['test*.py'])")
        self.assert_filedeps(
            targets=["some/target"],
            expected={"some/target/BUILD", "some/target/test*.py"},
            globs=True,
        )

    def test_build_with_file_ext(self) -> None:
        self.create_file("some/target/BUILD.ext", contents="tgt()")
        self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD.ext"})

    def test_codegen_targets_use_protocol_files(self) -> None:
        # That is, don't output generated files.
        self.create_file("some/target/f.proto")
        self.add_to_build_file("some/target", "protobuf_library()")
        self.assert_filedeps(
            targets=["some/target"], expected={"some/target/BUILD", "some/target/f.proto"}
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
