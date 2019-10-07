# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.contrib.buildrefactor.buildozer_util import prepare_dependencies
from pants_test.task_test_base import TaskTestBase

from pants.contrib.buildrefactor.buildozer import Buildozer


class BuildozerTest(TaskTestBase):
    """Test the buildozer tool"""

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"java_library": JavaLibrary})

    @classmethod
    def task_type(cls):
        return Buildozer

    def setUp(self):
        super().setUp()

        self.targets = prepare_dependencies(self)

    def test_add_single_dependency(self):
        self._test_add_dependencies("b", ["/a/b/c"])

    def test_add_multiple_dependencies(self):
        self._test_add_dependencies("b", ["/a/b/c", "/d/e/f"])

    def test_remove_single_dependency(self):
        self._test_remove_dependencies("c", ["b"])

    def test_remove_multiple_dependencies(self):
        self._test_remove_dependencies("d", ["a", "b"])

    def test_custom_command_error(self):
        with self.assertRaises(TaskError):
            self._run_buildozer({"command": "foo", "add-dependencies": "boo"})

    def test_custom_command(self):
        new_build_name = "b_2"

        self._run_buildozer({"command": "set name {}".format(new_build_name)})
        self.assertInFile(new_build_name, os.path.join(self.build_root, "b/BUILD"))

    def test_multiple_addresses(self):
        roots = ["b", "c"]
        dependency_to_add = "/l/m/n"

        self._test_add_dependencies_with_targets([dependency_to_add], roots, None)

    def test_implicit_name(self):
        self.add_to_build_file("e", "java_library()")

        targets = {"e": self.make_target("e")}
        roots = ["e"]
        dependency_to_add = "/o/p/q"

        self._test_add_dependencies_with_targets([dependency_to_add], roots, targets)

    def test_implicit_name_among_rules(self):
        self.add_to_build_file("f", 'java_library(name="f")')
        self.add_to_build_file("g", 'java_library(name="g")')
        self.add_to_build_file("h", "java_library()")

        targets = {
            "e": self.make_target("e"),
            "g": self.make_target("g"),
            "h": self.make_target("h"),
        }
        roots = ["h"]
        dependency_to_add = "/r/s/t"

        self._test_add_dependencies_with_targets([dependency_to_add], roots, targets)

    def _test_add_dependencies(self, spec, dependencies_to_add):
        self._run_buildozer({"add_dependencies": " ".join(dependencies_to_add)})

        for dependency in dependencies_to_add:
            self.assertIn(
                dependency,
                self._build_file_dependencies(os.path.join(self.build_root, spec, "BUILD")),
            )

    def _test_add_dependencies_with_targets(self, dependencies_to_add, roots, targets):
        """
    Test that a dependency is (or dependencies are) added to a BUILD file with buildozer.
    This can run on multiple context roots and multiple target objects.
    """
        for dependency_to_add in dependencies_to_add:
            self._run_buildozer(
                {"add_dependencies": dependency_to_add}, roots=roots, targets=targets
            )

            for root in roots:
                self.assertInFile(dependency_to_add, os.path.join(self.build_root, root, "BUILD"))

    def _test_remove_dependencies(self, spec, dependencies_to_remove):
        self._run_buildozer({"remove_dependencies": " ".join(dependencies_to_remove)}, roots=[spec])

        for dependency in dependencies_to_remove:
            self.assertNotIn(
                dependency,
                self._build_file_dependencies(os.path.join(self.build_root, spec, "BUILD")),
            )

    def _run_buildozer(self, options, roots=("b",), targets=None):
        """Run buildozer on the specified context roots and target objects.

    roots -- the context roots supplied to buildozer (default ['b'])
    targets -- the targets buildozer will run on (defaults to self.targets)
    """
        self.set_options(**options)

        targets = self.targets if targets is None else targets
        target_roots = []
        for root in roots:
            target_roots.append(targets[root])

        self.create_task(self.context(target_roots=target_roots)).execute()

    @staticmethod
    def _build_file_dependencies(build_file):
        with open(build_file, "r") as f:
            source = f.read()

        dependencies = re.compile("dependencies+.?=+.?\[([^]]*)").findall(source)

        return (
            "".join(dependencies[0].replace('"', "").split()).split(",")
            if len(dependencies) > 0
            else dependencies
        )
