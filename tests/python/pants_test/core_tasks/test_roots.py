# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.core_tasks.roots import ListRoots
from pants.source.source_root import SourceRootConfig
from pants_test.subsystem.subsystem_util import subsystem_instance
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ListRootsTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return ListRoots

  def _add_source_root(self, source_root_config, path, langs):
    os.makedirs(os.path.join(get_buildroot(), path))
    source_root_config.get_source_roots().add_source_root(path, langs)

  def test_no_langs(self):
    with subsystem_instance(SourceRootConfig) as source_root_config:
      self._add_source_root(source_root_config, 'fakeroot', tuple())
      self.assert_console_output('fakeroot: *')

  def test_single_source_root(self):
    with subsystem_instance(SourceRootConfig) as source_root_config:
      self._add_source_root(source_root_config, 'fakeroot', ('lang1', 'lang2'))
      self.assert_console_output('fakeroot: lang1,lang2')

  def test_multiple_source_roots(self):
    with subsystem_instance(SourceRootConfig) as source_root_config:
      self._add_source_root(source_root_config, 'fakerootA', ('lang1',))
      self._add_source_root(source_root_config, 'fakerootB', ('lang2',))
      self.assert_console_output('fakerootA: lang1', 'fakerootB: lang2')
