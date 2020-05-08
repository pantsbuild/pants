# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partialmethod
from typing import List, Optional

from pants.backend.jvm.target_types import JarLibrary, JavaLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary as JarLibraryV1
from pants.backend.jvm.targets.java_library import JavaLibrary as JavaLibraryV1
from pants.backend.project_info.dependencies import Dependencies, DependencyType, rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.backend.python.targets.python_requirement_library import (
    PythonRequirementLibrary as PythonRequirementLibraryV1,
)
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.java.jar.jar_dependency import JarDependency
from pants.python.python_requirement import PythonRequirement
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class DependenciesIntegrationTest(GoalRuleTestBase):
    goal_cls = Dependencies

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(
            targets={
                "jar_library": JarLibraryV1,
                "java_library": JavaLibraryV1,
                "python_library": PythonLibraryV1,
                "python_requirement_library": PythonRequirementLibraryV1,
            },
            objects={"jar": JarDependency, "python_requirement": PythonRequirement},
        )

    @classmethod
    def target_types(cls):
        return [JarLibrary, JavaLibrary, PythonLibrary, PythonRequirementLibrary]

    @classmethod
    def rules(cls):
        return (*super().rules(), *rules())

    _create_library = partialmethod(GoalRuleTestBase.create_library, name="target", sources=[])

    def create_java_library(self, path: str, *, dependencies: Optional[List[str]] = None) -> None:
        self._create_library(
            path=path, target_type=JavaLibrary.alias, dependencies=dependencies or []
        )

    def create_python_library(self, path: str, *, dependencies: Optional[List[str]] = None) -> None:
        self._create_library(
            path=path, target_type=PythonLibrary.alias, dependencies=dependencies or []
        )

    def create_jar_library(self, name: str, *, include_revision: bool = True) -> None:
        jar = (
            f"jar('org.example', {repr(name)}, '1.0.0')"
            if include_revision
            else f"jar('org.example', {repr(name)})"
        )
        self.add_to_build_file(f"3rdparty/jvm/{name}", f"jar_library(jars=[{jar}])")

    def create_python_requirement_library(self, name: str) -> None:
        self.create_library(
            path=f"3rdparty/python/{name}",
            target_type="python_requirement_library",
            name=name,
            requirements=f"[python_requirement('{name}==1.0.0')]",
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
            path="some/target", dependencies=["dep/target", "3rdparty/python/req1"]
        )
        self.create_python_library(
            path="some/other/target", dependencies=["some/target", "3rdparty/python/req2"]
        )

        # `--type=source`
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/python/req2:req2", "some/target:target"],
            dependency_type=DependencyType.SOURCE,
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=[
                "3rdparty/python/req2:req2",
                "some/target:target",
                "3rdparty/python/req1:req1",
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
            expected=["3rdparty/python/req2:req2", "some/target:target", "req2==1.0.0"],
            transitive=False,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=[
                "some/target:target",
                "dep/target:target",
                "3rdparty/python/req1:req1",
                "3rdparty/python/req2:req2",
                "req1==1.0.0",
                "req2==1.0.0",
            ],
            transitive=True,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        )

    def test_jars(self) -> None:
        self.create_jar_library(name="req1")
        self.create_jar_library(name="req2", include_revision=False)
        self.create_java_library(path="dep/target", dependencies=["3rdparty/jvm/req1"])
        self.create_java_library(
            path="some/target", dependencies=["3rdparty/jvm/req2", "dep/target"]
        )

        self.assert_dependencies(
            target="some/target",
            expected=["3rdparty/jvm/req2:req2", "dep/target:target", "org.example:req2"],
            transitive=False,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        )
        self.assert_dependencies(
            target="some/target",
            expected=[
                "dep/target:target",
                "3rdparty/jvm/req1:req1",
                "3rdparty/jvm/req2:req2",
                "org.example:req1:1.0.0",
                "org.example:req2",
            ],
            transitive=True,
            dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        )
