# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.project_info.tasks.ide_gen import SourceSet
from pants.backend.project_info.tasks.idea_gen import IdeaGen
from pants.base.source_root import SourceRoot
from pants_test.base_test import BaseTest


class IdeaGenTest(BaseTest):
  def test_sibling_is_test(self):
    SourceRoot.register("src/java", JavaLibrary)
    SourceRoot.register("src/resources", Resources)
    SourceRoot.register("tests/java", JavaTests, JavaLibrary)
    SourceRoot.register("tests/resources", Resources)

    src_java = SourceSet("repo-root", "src/java/com/pats", "project/lib", False)
    self.assertFalse(IdeaGen._sibling_is_test(src_java))

    src_resources = SourceSet("repo-root", "src/resources/org/pantsbuild", "project/lib", False,
                             'java-resource')
    self.assertFalse(IdeaGen._sibling_is_test(src_resources))

    # Surprise! It doesn't matter what you pass for is_test when constructing the source set,
    # its detecting that one of the siblings under /tests/ is configured with a JavaTests target.
    tests_java = SourceSet("repo-root", "tests/java/org/pantsbuild", "project/lib", False)
    self.assertTrue(IdeaGen._sibling_is_test(tests_java))

    tests_resources = SourceSet("repo-root", "tests/resources/org/pantsbuild", "project/lib", False)
    self.assertTrue(IdeaGen._sibling_is_test(tests_resources))
