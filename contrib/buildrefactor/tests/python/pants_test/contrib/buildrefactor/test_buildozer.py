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
    roots = ['b', 'c']
    dependency_to_add = '/l/m/n'

    self._test_add_dependencies_with_targets([dependency_to_add], roots, None)

  def test_implicit_name(self):
    self.add_to_build_file('e', 'java_library()')

    targets={}
    targets['e'] = self.make_target('e')
    roots = ['e']
    dependency_to_add = '/o/p/q'

    self._test_add_dependencies_with_targets([dependency_to_add], roots, targets)

  def test_implicit_name_among_rules(self):
    self.add_to_build_file('f', 'java_library(name="f")')
    self.add_to_build_file('g', 'java_library(name="g")')
    self.add_to_build_file('h', 'java_library()')

    targets={}
    targets['e'] = self.make_target('e')
    targets['g'] = self.make_target('g')
    targets['h'] = self.make_target('h')
    roots = ['h']
    dependency_to_add = '/r/s/t'

    self._test_add_dependencies_with_targets([dependency_to_add], roots, targets)

  def _test_add_dependencies(self, spec, dependencies_to_add):
    self._run_buildozer({ 'add_dependencies': ' '.join(dependencies_to_add) })

    for dependency in dependencies_to_add:
      self.assertIn(dependency, self._build_file_dependencies('{}/{}/BUILD'.format(self.build_root, spec)))

  def _test_add_dependencies_with_targets(self, dependencies_to_add, roots, targets):
    for dependency_to_add in dependencies_to_add:
      self._run_buildozer({ 'add_dependencies': dependency_to_add }, roots=roots, targets=targets)

    for root in roots:
      self.assertInFile(dependency_to_add, '{}/{}/BUILD'.format(self.build_root, root))

  def _test_remove_dependencies(self, spec, dependencies_to_remove):
    self._run_buildozer({ 'remove_dependencies': ' '.join(dependencies_to_remove) }, roots=[spec])

    for dependency in dependencies_to_remove:
      self.assertNotIn(dependency, self._build_file_dependencies('{}/{}/BUILD'.format(self.build_root, spec)))

  def _run_buildozer(self, options, roots=['b'], targets=None):
    targets = self.targets if targets == None else targets

    self.set_options(**options)

    target_roots = []

    for root in roots:
      target_roots.append(targets[root])

    self.create_task(self.context(target_roots=target_roots)).execute()

  def _build_file_dependencies(self, build_file):
    with open(build_file) as f:
      source = f.read()

    dependencies = re.compile('dependencies+.?=+.?\[([^]]*)').findall(source)

    return ''.join(dependencies[0].replace('\"', '').split()).split(',') if len(dependencies) > 0 else dependencies
