# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.project_info.rules import dependencies
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.python.python_requirement import PythonRequirement
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class DependenciesIntegrationTest(GoalRuleTestBase):
    goal_cls = dependencies.Dependencies

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(
            targets={
                "python_library": PythonLibrary,
                "python_requirement_library": PythonRequirementLibrary,
            },
            objects={"python_requirement": PythonRequirement,},
        )

    @classmethod
    def rules(cls):
        return super().rules() + dependencies.rules()

    def create_python_library(self, path: str, *, dependencies: Optional[List[str]] = None) -> None:
        self.create_library(
            path=path, target_type="python_library", name="target", dependencies=dependencies or []
        )

    def create_python_requirement_library(self, name: str) -> None:
        self.create_library(
            path=f"3rdparty/{name}",
            target_type="python_requirement_library",
            name=name,
            requirements=f"[python_requirement('{name}==1.0.0')]",
        )

    def assert_dependencies(
        self,
        *,
        target: str,
        expected: List[str],
        transitive: bool = True,
        dependency_type: str = "source",
    ) -> None:
        env = {"PANTS_BACKEND_PACKAGES2": "pants.backend.project_info"}
        args = [f"--type={dependency_type}"]
        if transitive:
            args.append("--transitive")
        self.assert_console_output(*expected, args=[*args, target], env=env)

    def test_no_target(self):
        self.assert_dependencies(
            target="", expected=[], transitive=False,
        )

    def test_no_dependencies(self):
        self.create_python_library(path="some/target")
        self.assert_dependencies(
            target="some/target", expected=[], transitive=False,
        )
        self.assert_dependencies(
            target="some/target", expected=[], transitive=True,
        )

    def test_dependencies_source(self):
        self.create_python_requirement_library(name="foo")
        self.create_python_requirement_library(name="bar")
        self.create_python_library(path="dep/target")
        self.create_python_library(path="some/target", dependencies=["dep/target", "3rdparty/foo:foo"])
        self.create_python_library(path="some/other/target", dependencies=["some/target", "3rdparty/bar:bar"])
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/bar:bar", "some/target:target"],
            transitive=False,
            dependency_type="source",
        )

    def test_dependencies_source_transitive(self):
        self.create_python_requirement_library(name="foo")
        self.create_python_requirement_library(name="bar")
        self.create_python_library(path="dep/target")
        self.create_python_library(path="some/target", dependencies=["dep/target", "3rdparty/foo:foo"])
        self.create_python_library(path="some/other/target", dependencies=["some/target", "3rdparty/bar:bar"])
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/bar:bar", "some/target:target", "3rdparty/foo:foo", "dep/target:target"],
            transitive=True,
            dependency_type="source",
        )


    def test_dependencies_3rdparty(self):
        self.create_python_requirement_library(name="foo")
        self.create_python_requirement_library(name="bar")
        self.create_python_library(path="dep/target")
        self.create_python_library(
            path="some/target", dependencies=["dep/target", "3rdparty/foo:foo"]
        )
        self.create_python_library(
            path="some/other/target", dependencies=["some/target", "3rdparty/bar:bar"]
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=["bar==1.0.0"],
            transitive=False,
            dependency_type="3rdparty",
        )

    def test_dependencies_3rdparty_transitive(self):
        self.create_python_requirement_library(name="foo")
        self.create_python_requirement_library(name="bar")
        self.create_python_library(path="dep/target")
        self.create_python_library(
            path="some/target", dependencies=["dep/target", "3rdparty/foo:foo"]
        )
        self.create_python_library(
            path="some/other/target", dependencies=["some/target", "3rdparty/bar:bar"]
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=["bar==1.0.0", "foo==1.0.0"],
            transitive=True,
            dependency_type="3rdparty",
        )

    def test_dependencies_source_and_3rdparty(self):
        self.create_python_requirement_library(name="foo")
        self.create_python_requirement_library(name="bar")
        self.create_python_library(path="dep/target")
        self.create_python_library(
            path="some/target", dependencies=["dep/target", "3rdparty/foo:foo"]
        )
        self.create_python_library(
            path="some/other/target", dependencies=["some/target", "3rdparty/bar:bar"]
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/bar:bar", "some/target:target", "bar==1.0.0"],
            transitive=False,
            dependency_type="source-and-3rdparty",
        )

    def test_dependencies_source_and_3rdparty_transitive(self):
        self.create_python_requirement_library(name="foo")
        self.create_python_requirement_library(name="bar")
        self.create_python_library(path="dep/target")
        self.create_python_library(
            path="some/target", dependencies=["dep/target", "3rdparty/foo:foo"]
        )
        self.create_python_library(
            path="some/other/target", dependencies=["some/target", "3rdparty/bar:bar"]
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=[
                "some/target:target",
                "dep/target:target",
                "3rdparty/foo:foo",
                "3rdparty/bar:bar",
            ],
            transitive=True,
            dependency_type="source-and-3rdparty",
        )


        self.assert_dependencies(
            target="some/other/target",
            expected=["bar==1.0.0"],
            transitive=False,
            dependency_type="3rdparty",
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=["3rdparty/bar:bar", "bar==1.0.0"],
            transitive=False,
            dependency_type="source-and-3rdparty",
        )
        self.assert_dependencies(
            target="some/other/target",
            expected=["some/target:target", "3rdparty/bar"],
            transitive=False,
            dependency_type="source-and-3rdparty",
        )

