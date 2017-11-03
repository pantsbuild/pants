# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.binaries.binary_util import BinaryUtil
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.contrib.buildrefactor.buildozer_util import assertInFile, prepare_dependencies
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.buildrefactor.meta_rename import MetaRename


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
    self.meta_rename = self.create_task(self.context(target_roots=prepare_dependencies(self).values()))

  def test_update_original_build_name(self):
    init_subsystem(BinaryUtil.Factory)

    build_file = '{}/{}/BUILD'.format(self.build_root, self.spec_path)

    self.meta_rename.execute()

    assertInFile(self, self.new_name, build_file)

  def test_update_dependee_references(self):
    init_subsystem(BinaryUtil.Factory)

    self.meta_rename.execute()

    for target in ['a', 'b', 'c']:
      assertInFile(self, self.new_name, '{}/{}/BUILD'.format(self.build_root, target))
