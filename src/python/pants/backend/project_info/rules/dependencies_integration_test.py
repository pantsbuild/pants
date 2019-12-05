# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.project_info.rules import dependencies
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.testutil.console_rule_test_base import ConsoleRuleTestBase


class FastDependenciesTest(ConsoleRuleTestBase):
  goal_cls = dependencies.Dependencies

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(
      targets={
        "python_library": PythonLibrary,
      },
    )

  @classmethod
  def rules(cls):
    return super().rules() + dependencies.rules()

  def create_python_library(
    self, path: str,
    *,
    dependencies: Optional[List[str]] = None
  ) -> None:
    self.create_library(
      path=path,
      target_type="python_library",
      name="target",
      dependencies=dependencies or []
    )

  def assert_dependencies(self, *, target: str, expected: List[str], transitive: bool = True) -> None:
    args = ["--no-transitive"] if not transitive else []
    self.assert_console_output(*expected, args=[*args, target])

  def test_no_target(self):
    self.assert_dependencies(
      target='',
      expected=[],
      transitive=False,
    )

  def test_no_dependencies(self):
    self.create_python_library(path="some/target")
    self.assert_dependencies(
      target="some/target",
      expected=[],
      transitive=False,
    )
    self.assert_dependencies(
      target="some/target",
      expected=["some/target:target"],
      transitive=True,
    )

  def test_dependencies(self):
    self.create_python_library(path="dep/target")
    self.create_python_library(path="some/target", dependencies=["dep/target"])
    self.assert_dependencies(
      target="some/target",
      expected=["dep/target:target"],
      transitive=False,
    )

  def test_dependencies_transitive(self):
    self.create_python_library(path="dep/target")
    self.create_python_library(path="some/target", dependencies=["dep/target"])
    self.create_python_library(path="some/other/target", dependencies=["some/target"])
    self.assert_dependencies(
      target="some/other/target",
      expected=[
        "some/target:target",
      ],
      transitive=False,
    )
    self.assert_dependencies(
      target="some/other/target",
      expected=[
        "dep/target:target",
        "some/other/target:target",
        "some/target:target",
      ],
      transitive=True,
    )
