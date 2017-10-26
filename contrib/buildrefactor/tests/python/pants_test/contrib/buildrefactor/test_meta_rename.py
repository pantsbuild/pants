# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.binaries.binary_util import BinaryUtil
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.contrib.buildrefactor.meta_rename import MetaRename
from pants_test.contrib.buildrefactor.buildozer_util import (clean_build_directory, assertInFile)
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.tasks.task_test_base import TaskTestBase


class MetaRenameTest(TaskTestBase):
  """Test renaming in MetaRename"""

  @classmethod
  def task_type(cls):
    return MetaRename

  @property
  def alias_groups(self):
    return BuildFileAliases(targets={ 'java_library': JavaLibrary })

  def setUp(self):
    super(MetaRenameTest, self).setUp()

    self.new_name = 'goo'
    self.spec_path = 'a'
    self.set_options(**{ 'from': '{}:a'.format(self.spec_path), 'to': '{}:{}'.format(self.spec_path, self.new_name) })
    self.meta_rename = self.create_task(self.context(target_roots=self._prepare_dependencies()))

  def test_update_original_build_name(self):
    init_subsystem(BinaryUtil.Factory)

    build_file = '{}/{}/BUILD'.format(self.build_root, self.spec_path)

    clean_build_directory(self.build_root)
    self.meta_rename.execute()

    assertInFile(self, self.new_name, build_file)

  def test_update_dependee_references(self):
    init_subsystem(BinaryUtil.Factory)

    clean_build_directory(self.build_root)
    self.meta_rename.execute()

    assertInFile(self, self.new_name, '{}/{}/BUILD'.format(self.build_root, 'b'))
    assertInFile(self, self.new_name, '{}/{}/BUILD'.format(self.build_root, 'c'))
    assertInFile(self, self.new_name, '{}/{}/BUILD'.format(self.build_root, 'd'))

  def _prepare_dependencies(self):
    targets = {}

    targets['a'] = self.create_library('a', 'java_library', 'a', ['A.java'])
    targets['b'] = self.create_library('b', 'java_library', 'b', ['B.java'], dependencies=['a:a'])
    targets['c'] = self.create_library('c', 'java_library', 'c', ['C.java'], dependencies=['a:a'])
    targets['d'] = self.create_library('d', 'java_library', 'd', ['D.java'], dependencies=['a:a'])

    return targets.values()
