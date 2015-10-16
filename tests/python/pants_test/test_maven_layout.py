# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.maven_layout.maven_layout import maven_layout
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.source.source_root import SourceRootConfig
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class MavenLayoutTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'java_library': JavaLibrary,
        'junit_tests': JavaTests,
      },
      context_aware_object_factories={
        'maven_layout': maven_layout,
      }
    )

  def setUp(self):
    super(MavenLayoutTest, self).setUp()
    self.add_to_build_file('projectB/src/test/scala',
                           'junit_tests(name="test", sources=["a/source"])')
    self.create_file('projectB/BUILD', 'maven_layout()')

    self.add_to_build_file('projectA/subproject/src/main/java',
                           'java_library(name="test", sources=[])')
    self.create_file('BUILD', 'maven_layout("projectA/subproject")')

  def test_layout_here(self):
    with subsystem_instance(SourceRootConfig):
      self.assertEqual('projectB/src/test/scala',
                       self.target('projectB/src/test/scala:test').target_base)

  def test_subproject_layout(self):
    with subsystem_instance(SourceRootConfig):
      self.assertEqual('projectA/subproject/src/main/java',
                       self.target('projectA/subproject/src/main/java:test').target_base)
