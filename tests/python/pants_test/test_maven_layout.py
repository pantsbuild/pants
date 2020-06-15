# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.source.source_root import SourceRootConfig
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.test_base import TestBase


# Note: There is no longer any special maven_layout directive.  Maven layouts should just
# work out of the box.  This test exists just to prove that statement true.
class MavenLayoutTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"java_library": JavaLibrary, "junit_tests": JUnitTests})

    def setUp(self):
        super().setUp()
        init_subsystems(
            [SourceRootConfig, JUnit], {"source": {"root_patterns": ["src/main/*", "src/test/*"]}}
        )
        self.create_file("projectB/src/test/scala/a/source")
        self.add_to_build_file(
            "projectB/src/test/scala", 'junit_tests(name="test", sources=["a/source"])'
        )

        self.add_to_build_file(
            "projectA/subproject/src/main/java", 'java_library(name="test", sources=[])'
        )

    def test_layout_here(self):
        self.assertEqual(
            "projectB/src/test/scala", self.target("projectB/src/test/scala:test").target_base
        )

    def test_subproject_layout(self):
        self.assertEqual(
            "projectA/subproject/src/main/java",
            self.target("projectA/subproject/src/main/java:test").target_base,
        )
