# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Set

from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.rules.core import filedeps
from pants_test.console_rule_test_base import ConsoleRuleTestBase


class FileDepsTest(ConsoleRuleTestBase):

  goal_cls = filedeps.Filedeps

  @classmethod
  def rules(cls):
    return super().rules() + filedeps.rules()

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(
      targets={
        'target': Target,
        'python_library': PythonLibrary,
      },
    )

  def create_python_library(
    self, path: str,
    *,
    sources: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None
  ) -> None:
    self.create_library(
      path=path,
      target_type="python_library",
      name="target",
      sources=sources or [],
      dependencies=dependencies or []
    )

  def assert_filedeps(self, *, targets: List[str], expected: Set[str]):
    self.assert_console_output(*expected, args=["--no-filedeps-absolute"] + targets)

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
      expected={"some/target/BUILD", "some/target/file1.py", "some/target/file2.py"}
    )

  def test_one_target_no_source_one_dep(self) -> None:
    self.create_python_library("dep/target", sources=["file.py"])
    self.create_python_library("some/target", dependencies=["dep/target"])
    self.assert_filedeps(
      targets=["some/target"],
      expected={"some/target/BUILD", "dep/target/BUILD", "dep/target/file.py"}
    )

  def test_one_target_one_source_with_dep(self) -> None:
    self.create_python_library("dep/target", sources=["file.py"])
    self.create_python_library("some/target", sources=["file.py"], dependencies=["dep/target"])
    self.assert_filedeps(
      targets=["some/target"],
      expected={
        "some/target/BUILD", "some/target/file.py", "dep/target/BUILD", "dep/target/file.py"
      }
    )

  def test_multiple_targets_one_source(self) -> None:
    self.create_python_library("some/target", sources=["file.py"])
    self.create_python_library("other/target", sources=["file.py"])
    self.assert_filedeps(
      targets=["some/target", "other/target"],
      expected={
        "some/target/BUILD", "some/target/file.py", "other/target/BUILD", "other/target/file.py"
      }
    )

  def test_multiple_targets_one_source_with_dep(self) -> None:
    self.create_python_library("dep1/target", sources=["file.py"])
    self.create_python_library("dep2/target", sources=["file.py"])
    self.create_python_library("some/target", sources=["file.py"], dependencies=["dep1/target"])
    self.create_python_library("other/target", sources=["file.py"], dependencies=["dep2/target"])
    self.assert_filedeps(
      targets=["some/target", "other/target"],
      expected={
        "some/target/BUILD",
        "some/target/file.py",
        "other/target/BUILD",
        "other/target/file.py",
        "dep1/target/BUILD",
        "dep1/target/file.py",
        "dep2/target/BUILD",
        "dep2/target/file.py",
      }
    )

  def test_multiple_targets_one_source_overlapping(self) -> None:
    self.create_python_library("dep/target", sources=["file.py"])
    self.create_python_library("some/target", sources=["file.py"], dependencies=["dep/target"])
    self.create_python_library("other/target", sources=["file.py"], dependencies=["dep/target"])
    self.assert_filedeps(
      targets=["some/target", "other/target"],
      expected={
        "some/target/BUILD",
        "some/target/file.py",
        "other/target/BUILD",
        "other/target/file.py",
        "dep/target/BUILD",
        "dep/target/file.py",
      }
    )

  def test_build_with_file_ext(self):
    self.create_file("some/target/BUILD.ext", contents="target()")
    self.assert_filedeps(targets=["some/target"], expected={"some/target/BUILD.ext"})
