# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.buildrefactor.buildozer import Buildozer


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

  def test_add_single_dependency(self):
    self._test_add_dependencies('b', '/a/b/c')

  def test_add_multiple_dependencies(self):
    self._test_add_dependencies('b', '/a/b/c /d/e/f')

  def test_remove_single_dependency(self):
    self._test_remove_dependencies('c', 'b')

  def test_remove_multiple_dependencies(self):
    self._test_remove_dependencies('d', 'a b')

  def test_custom_command(self):
    build_file = self.build_root + '/b/BUILD'
    new_build_name = 'b_2'

    self._clean_build_file(build_file)
    self._test_buildozer_execution({ 'command': 'set name {}'.format(new_build_name) })

    with open(build_file) as f:
      build_source = f.read()

    self.assertIn(new_build_name, build_source)

  def test_custom_command_error(self):
    with self.assertRaises(TaskError):
      self._test_buildozer_execution({ 'command': 'foo', 'add-dependencies': 'boo' })

  def _test_add_dependencies(self, spec_path, dependencies_to_add):
    build_file = self.build_root + '/{}/BUILD'.format(spec_path)

    self._clean_build_file(build_file)
    self._test_buildozer_execution({ 'add_dependencies': dependencies_to_add })

    for dependency in dependencies_to_add.split(' '):
      self.assertIn(dependency, self._build_file_dependencies(build_file))

  def _test_remove_dependencies(self, spec_path, dependencies_to_remove):
    build_file = self.build_root + '/b/BUILD'

    self._clean_build_file(build_file)
    self._test_buildozer_execution({ 'remove_dependencies': dependencies_to_remove })

    for dependency in dependencies_to_remove.split(' '):
      self.assertNotIn(dependency, self._build_file_dependencies(build_file))

  def _test_buildozer_execution(self, options):
    self.set_options(**options)
    self.create_task(self.context(target_roots=self.targets['b'])).execute()

  def _prepare_dependencies(self):
    targets = {}

    targets['a'] = self.create_library('a', 'java_library', 'a', ['A.java'])
    targets['b'] = self.create_library('b', 'java_library', 'b', ['B.java'])
    targets['c'] = self.create_library('c', 'java_library', 'c', ['C.java'], dependencies=['b'])
    targets['d'] = self.create_library('d', 'java_library', 'd', ['D.java'], dependencies=['a', 'b'])

    return targets

  def _clean_build_file(self, build_file):
    with open(build_file) as f:
      source = f.read()

    new_source = source.replace('u\'', '\'')

    with open(build_file, 'w') as new_file:
      new_file.write(new_source)

  def _build_file_dependencies(self, build_file):
    with open(build_file) as f:
      source = f.read()

    dependencies = re.compile('dependencies+.?=+.?\[([^]]*)').findall(source)

    return ''.join(dependencies[0].replace('\"', '').split()).split(',') if len(dependencies) > 0 else dependencies
