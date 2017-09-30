# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.backend.python.buildozer.buildozer import Buildozer
from pants_test.tasks.task_test_base import TaskTestBase


class BuildozerTest(TaskTestBase):
  """Test the buildozer tool"""

  @property
  def alias_groups(self):
    return BuildFileAliases(targets={ 'java_library': JavaLibrary })

  @classmethod
  def task_type(cls):
    return Buildozer

  def setUp(self):
    super(BuildozerTest, self).setUp()

    self.targets = self._prepare_dependencies()

  def test_add_dependency(self):
    mock_dependency = '/a/b/c'
    build_file = self.build_root + '/b/BUILD'

    self._clean_build_file(build_file)
    self._test_buildozer_execution({ 'add': mock_dependency, 'location': '//b:b' })
    self.assertIn(mock_dependency, self._build_file_dependencies(build_file))

  def test_remove_dependency(self):
    dependency_to_remove = 'a'    
    build_file = self.build_root + '/b/BUILD'

    self._clean_build_file(build_file)
    self._test_buildozer_execution({ 'remove': dependency_to_remove, 'location': '//b:b' })    
    self.assertNotIn(dependency_to_remove, self._build_file_dependencies(build_file))

  def _test_buildozer_execution(self, options):
    self.set_options(**options)
    self.create_task(self.context(target_roots=self.targets)).execute()

  def _prepare_dependencies(self):
    targets = {}

    targets['a'] = self.create_library('a', 'java_library', 'a', ['A.java'])
    targets['b'] = self.create_library('b', 'java_library', 'b', ['B.java'], dependencies=['a'])

    return targets.values()

  def _clean_build_file(self, build_file):
    with open(build_file) as f:
      source = f.read()

    new_source = source.replace('u\'', '\'')
    
    with open(build_file, 'w') as new_file:
      new_file.write(new_source)
  
  def _build_file_dependencies(self, build_file):
    with open(build_file) as f:
      source = f.read()

    dependencies = re.compile('dependencies\ =\ \[([^]]*)').findall(source)

    return ''.join(dependencies[0].replace('\"', '').split()).split(',') if len(dependencies) > 0 else dependencies
