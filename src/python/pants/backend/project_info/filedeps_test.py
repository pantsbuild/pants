# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Set

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
            args.append("--filedeps-globs")
        if transitive:
            args.append("--filedeps-transitive")
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
