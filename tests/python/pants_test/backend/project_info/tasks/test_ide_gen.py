# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.project_info.tasks.ide_gen import Project, SourceSet
from pants.base.source_root import SourceRoot
from pants_test.base_test import BaseTest


class IdeGenTest(BaseTest):

  def test_collapse_source_root(self):
    source_set_list = []
    self.assertEquals([], Project._collapse_by_source_root(source_set_list))

    SourceRoot.register("src/java", JavaLibrary)
    SourceRoot.register("tests/java", JavaTests)
    source_sets = [
      SourceSet("/repo-root", "src/java", "org/pantsbuild/app", False),
      SourceSet("/repo-root", "tests/java", "org/pantsbuild/app", True),
      SourceSet("/repo-root", "some/other", "path", False),
    ]

    results = Project._collapse_by_source_root(source_sets)

    self.assertEquals(SourceSet("/repo-root", "src/java", "", False), results[0])
    self.assertFalse(results[0].is_test)
    self.assertEquals(SourceSet("/repo-root", "tests/java", "", True), results[1])
    self.assertTrue(results[1].is_test)
    # If there is no registered source root, the SourceSet should be returned unmodified
    self.assertEquals(source_sets[2], results[2])
    self.assertFalse(results[2].is_test)

  def test_source_set(self):
    source_set1 = SourceSet("repo-root", "path/to/build", "org/pantsbuild/project", False)
    # only the first 3 parameters are considered keys
    self.assertEquals(("repo-root", "path/to/build", "org/pantsbuild/project"), source_set1._key_tuple)
    source_set2 = SourceSet("repo-root", "path/to/build", "org/pantsbuild/project", True)
    # Don't consider the test flag
    self.assertEquals(source_set1, source_set2)
