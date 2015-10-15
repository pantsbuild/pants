# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.core.tasks.roots import ListRoots
from pants.base.build_environment import get_buildroot
from pants.source.source_root import SourceRootConfig, SourceRoots
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


@contextmanager
def register_sourceroot():
  try:
    yield SourceRoots.register
  except (ValueError, IndexError) as e:
    print('SourceRoot Registration Failed.')
    raise e
  finally:
    SourceRoots.reset()


class ListRootsTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return ListRoots

  def setUp(self):
    super(ListRootsTest, self).setUp()
    self.set_options_for_scope(SourceRootConfig.options_scope, langs=[],
                               source_root_parents=[], test_root_parents=[],
                               source_root_patterns={}, test_root_patterns={},
                               source_roots={}, test_roots={})
    self._context = self.context()

  def _add_source_root(self, path, langs):
    os.makedirs(os.path.join(get_buildroot(), path))
    self._context.source_roots.register(path, langs)

  def _assert_output(self, expected):
    self.assertEqual(expected, self.execute_console_task_given_context(self._context))

  def test_roots_without_register(self):
    try:
      self._assert_output([])
    except AssertionError:
      self.fail('./pants goal roots failed without any registered SourceRoot.')

  def test_no_langs(self):
    self._add_source_root('fakeroot', tuple())
    self._assert_output(['fakeroot: *'])

  def test_single_source_root(self):
    self._add_source_root('fakeroot', ('lang1', 'lang2'))
    self._assert_output(['fakeroot: lang1,lang2'])

  def test_multiple_source_root(self):
    self._add_source_root('fakerootA', ('lang1',))
    self._add_source_root('fakerootB', ('lang2',))
    self._assert_output(['fakerootA: lang1', 'fakerootB: lang2'])
