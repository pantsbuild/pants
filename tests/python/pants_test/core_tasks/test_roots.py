# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.core_tasks.roots import ListRoots
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ListRootsTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return ListRoots

  def _create_source_roots(self, source_root_dict):
    self.set_options_for_scope('source', source_roots=source_root_dict)
    for dir in source_root_dict.keys():
      os.makedirs(os.path.join(get_buildroot(), dir))

  def test_no_langs(self):
    self._create_source_roots({'fakeroot': tuple()})
    self.assert_console_output('fakeroot: *')

  def test_single_source_root(self):
    self._create_source_roots({'fakeroot': ('lang1', 'lang2')})
    self.assert_console_output('fakeroot: lang1,lang2')

  def test_multiple_source_roots(self):
    self._create_source_roots({'fakerootA': ('lang1',),
                               'fakerootB': ('lang2',)})
    self.assert_console_output('fakerootA: lang1', 'fakerootB: lang2')
