# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional

from pants.backend.project_info.dependencies import Dependencies, DependencyType, rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.python.python_requirement import PythonRequirement
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class DependenciesIntegrationTest(GoalRuleTestBase):
    goal_cls = Dependencies

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(objects={"python_requirement": PythonRequirement})

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary]

    @classmethod
    def rules(cls):
        return (*super().rules(), *rules())

    def create_python_library(self, path: str, *, dependencies: Optional[List[str]] = None) -> None:
        self.add_to_build_file(
            path,
            f"python_library(name='target', sources=[], dependencies={dependencies or []})"
        )

    def create_python_requirement_library(self, name: str) -> None:
        self.add_to_build_file(
            f"3rdparty/python",
            dedent(
                f"""\
                python_requirement_library(
                    name='{name}',
                    requirements=[python_requirement('{name}==1.0.0')],
                )
                """
            )
        )

    def assert_dependencies(
        self,
        *,
        target: str,
        expected: List[str],
        transitive: bool = False,
        dependency_type: DependencyType = DependencyType.SOURCE,
    ) -> None:
        env = {"PANTS_BACKEND_PACKAGES2": "pants.backend.project_info"}
        args = [f"--type={dependency_type.value}"]
        if transitive:
            args.append("--transitive")
        self.assert_console_output(*expected, args=[*args, target], env=env)

    def test_no_target(self) -> None:
        self.assert_dependencies(target="", expected=[])

    def test_no_dependencies(self) -> None:
        self.create_python_library(path="some/target")
        self.assert_dependencies(target="some/target", expected=[])
        self.assert_dependencies(
            target="some/target", expected=[], transitive=True,
        )

    def test_python_dependencies(self) -> None:
        self.create_python_requirement_library(name="req1")
        self.create_python_requirement_library(name="req2")
        self.create_python_library(path="dep/target")
        self.create_python_library(
            path="some/target", dependencies=["dep/target", "3rdparty/python:req1"]
        )
        self.create_python_library(
            path="some/other/target", dependencies=["some/target", "3rdparty/python:req2"]
        )

        # `--type=source`
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/python:req2", "some/target:target"],
            dependency_type=DependencyType.SOURCE,
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=[
                "3rdparty/python:req2",
                "some/target:target",
                "3rdparty/python:req1",
                "dep/target:target",
            ],
            transitive=True,
            dependency_type=DependencyType.SOURCE,
        )

        # `--type=3rdparty`
        self.assert_dependencies(
            target="some/other/target",
            expected=["req2==1.0.0"],
            dependency_type=DependencyType.THIRD_PARTY,
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=["req1==1.0.0", "req2==1.0.0"],
            transitive=True,
            dependency_type=DependencyType.THIRD_PARTY,
        )

        # `--type=source-and-3rdparty`
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/python:req2", "some/target:target", "req2==1.0.0"],
            transitive=False,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=[
                "some/target:target",
                "dep/target:target",
                "3rdparty/python:req1",
                "3rdparty/python:req2",
                "req1==1.0.0",
                "req2==1.0.0",
            ],
            transitive=True,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        )
