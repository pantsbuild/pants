# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional

from pants.backend.project_info.dependencies import Dependencies, DependencyType, rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.testutil.test_base import TestBase


class DependenciesIntegrationTest(TestBase):
    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary]

    @classmethod
    def rules(cls):
        return (*super().rules(), *rules())

    def create_python_library(self, path: str, *, dependencies: Optional[List[str]] = None) -> None:
        self.add_to_build_file(
            path, f"python_library(name='target', sources=[], dependencies={dependencies or []})"
        )

    def create_python_requirement_library(self, name: str) -> None:
        self.add_to_build_file(
            "3rdparty/python",
            dedent(
                f"""\
                python_requirement_library(
                    name='{name}',
                    requirements=['{name}==1.0.0'],
                )
                """
            ),
        )

    def assert_dependencies(
        self,
        *,
        specs: List[str],
        expected: List[str],
        transitive: bool = False,
        dependency_type: DependencyType = DependencyType.SOURCE,
    ) -> None:
        args = [f"--type={dependency_type.value}"]
        if transitive:
            args.append("--transitive")
        result = self.run_goal_rule(Dependencies, args=[*args, *specs])
        assert result.stdout.splitlines() == expected

    def test_no_target(self) -> None:
        self.assert_dependencies(specs=[], expected=[])
        self.assert_dependencies(specs=[], expected=[], transitive=True)

    def test_no_dependencies(self) -> None:
        self.create_python_library(path="some/target")
        self.assert_dependencies(specs=["some/target"], expected=[])
        self.assert_dependencies(specs=["some/target"], expected=[], transitive=True)

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
            specs=["some/other/target"],
            dependency_type=DependencyType.SOURCE,
            expected=["3rdparty/python:req2", "some/target"],
        )
        self.assert_dependencies(
            specs=["some/other/target"],
            transitive=True,
            dependency_type=DependencyType.SOURCE,
            expected=["3rdparty/python:req1", "3rdparty/python:req2", "dep/target", "some/target"],
        )

        # `--type=3rdparty`
        self.assert_dependencies(
            specs=["some/other/target"],
            dependency_type=DependencyType.THIRD_PARTY,
            expected=["req2==1.0.0"],
        )
        self.assert_dependencies(
            specs=["some/other/target"],
            transitive=True,
            dependency_type=DependencyType.THIRD_PARTY,
            expected=["req1==1.0.0", "req2==1.0.0"],
        )

        # `--type=source-and-3rdparty`
        self.assert_dependencies(
            specs=["some/other/target"],
            transitive=False,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
            expected=["3rdparty/python:req2", "some/target", "req2==1.0.0"],
        )
        self.assert_dependencies(
            specs=["some/other/target"],
            transitive=True,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
            expected=[
                "3rdparty/python:req1",
                "3rdparty/python:req2",
                "dep/target",
                "some/target",
                "req1==1.0.0",
                "req2==1.0.0",
            ],
        )

        # Glob the whole repo. `some/other/target` should not be included because nothing depends
        # on it.
        self.assert_dependencies(
            specs=["::"],
            expected=["3rdparty/python:req1", "3rdparty/python:req2", "dep/target", "some/target"],
        )
        self.assert_dependencies(
            specs=["::"],
            transitive=True,
            expected=["3rdparty/python:req1", "3rdparty/python:req2", "dep/target", "some/target"],
        )
