# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.base.source_root import SourceRoot

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.tasks.ide_gen import Project, SourceSet
from pants.backend.jvm.tasks.idea_gen import IdeaGen
from pants.backend.core.targets.resources import Resources


from pants_test.base_test import BaseTest


class IdeGenTest(BaseTest):

  def test_collapse_source_root(self):
    source_set_list = []
    self.assertEquals([], Project._collapse_by_source_root(source_set_list))

    SourceRoot.register("src/java", JavaLibrary)
    SourceRoot.register("tests/java", JavaTests)
    source_sets = [
      SourceSet("/repo-root", "src/java", "com/pants/app", False),
      SourceSet("/repo-root", "tests/java", "com/pants/app", True),
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
    source_set1 = SourceSet("repo-root", "path/to/build", "com/pants/project", False)
    # only the first 3 parameters are considered keys
    self.assertEquals(("repo-root", "path/to/build", "com/pants/project"), source_set1._key_tuple)
    source_set2 = SourceSet("repo-root", "path/to/build", "com/pants/project", True)
    # Don't consider the test flag
    self.assertEquals(source_set1, source_set2)



class IdeaGenTest(BaseTest):
  def test_sibling_is_test(self):
    SourceRoot.register("src/java", JavaLibrary)
    SourceRoot.register("src/resources", Resources)
    SourceRoot.register("tests/java", JavaTests, JavaLibrary)
    SourceRoot.register("tests/resources", Resources)

    self.assertFalse(IdeaGen._sibling_is_test(SourceSet("repo-root", "src/java/com/pats", "project/lib", False)))
    self.assertFalse(IdeaGen._sibling_is_test(SourceSet("repo-root", "src/resources/com/pants", "project/lib", False)))
    # Surprise! It doesn't matter what you pass for is_test when constructing the source set,
    # its deteching that one of the siblings under /tests/ is configured with a JavaTests target.
    self.assertTrue(IdeaGen._sibling_is_test(SourceSet("repo-root", "tests/java/com/pants", "project/lib", False)))
    self.assertTrue(IdeaGen._sibling_is_test(SourceSet("repo-root", "tests/resources/com/pants", "project/lib", False)))
