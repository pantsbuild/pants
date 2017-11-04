# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.contrib.buildrefactor.buildozer_util import prepare_dependencies
from pants_test.subsystem.subsystem_util import init_subsystem
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

    self.targets = prepare_dependencies(self)

  def test_add_single_dependency(self):
    self._test_add_dependencies('b', ['/a/b/c'])

  def test_add_multiple_dependencies(self):
    self._test_add_dependencies('b', ['/a/b/c', '/d/e/f'])

  def test_remove_single_dependency(self):
    self._test_remove_dependencies('c', ['b'])

  def test_remove_multiple_dependencies(self):
    self._test_remove_dependencies('d', ['a', 'b'])

  def test_custom_command_error(self):
    with self.assertRaises(TaskError):
      self._run_buildozer({ 'command': 'foo', 'add-dependencies': 'boo' })

  def test_custom_command(self):
    new_build_name = 'b_2'

    self._run_buildozer({ 'command': 'set name {}'.format(new_build_name) })
    self.assertInFile(new_build_name, '{}/b/BUILD'.format(self.build_root))

  def test_execute_binary(self):
    init_subsystem(BinaryUtil.Factory)

    new_build_name = 'b_2'

    Buildozer.execute_binary('set name {}'.format(new_build_name), spec=Address.parse('b').spec)

    self.assertInFile(new_build_name, '{}/b/BUILD'.format(self.build_root))

  def test_multiple_addresses(self):
    targets = ['b', 'c']

    dependency_to_add = '/l/m/n'

    self._run_buildozer({ 'add_dependencies': dependency_to_add }, targets=targets)

    for target in targets:
      self.assertInFile(dependency_to_add, '{}/{}/BUILD'.format(self.build_root, target))

  def _test_add_dependencies(self, spec, dependencies_to_add):
    self._run_buildozer({ 'add_dependencies': ' '.join(dependencies_to_add) })

    for dependency in dependencies_to_add:
      self.assertIn(dependency, self._build_file_dependencies('{}/{}/BUILD'.format(self.build_root, spec)))

  def _test_remove_dependencies(self, spec, dependencies_to_remove):
    self._run_buildozer({ 'remove_dependencies': ' '.join(dependencies_to_remove) }, targets=[spec])

    for dependency in dependencies_to_remove:
      self.assertNotIn(dependency, self._build_file_dependencies('{}/{}/BUILD'.format(self.build_root, spec)))

  def _run_buildozer(self, options, targets=['b']):
    self.set_options(**options)

    target_roots = []

    for root in targets:
      target_roots.append(self.targets[root])

    self.create_task(self.context(target_roots=target_roots)).execute()

  def _build_file_dependencies(self, build_file):
    with open(build_file) as f:
      source = f.read()

    dependencies = re.compile('dependencies+.?=+.?\[([^]]*)').findall(source)

    return ''.join(dependencies[0].replace('\"', '').split()).split(',') if len(dependencies) > 0 else dependencies
