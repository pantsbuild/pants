# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.specs import DescendantAddresses
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.meta_rename import MetaRename
from pants_test.base_test import BaseTest
from pants_test.tasks.task_test_base import TaskTestBase
from pants.util.dirutil import safe_delete

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

    self.set_options(**{ 'from': '', 'to': '' })

    targets = self._prepare_dependencies()

    self.meta_rename = self.create_task(self.context(target_roots=targets))
    self.full_graph = self.meta_rename.dependency_graph()

  def test_dependency_graph(self):
    self.assertEqual(
      self.full_graph.__str__(),
      "defaultdict(<type 'set'>, {JavaLibrary(BuildFileAddress(a/BUILD, a)): set([BuildFileAddress(b/BUILD, b)])})"
    )

  def test_replace_in_file(self):
    _file = 'foo.txt'

    with open(_file, 'w') as new_file:
      new_file.write('bar foo')

    self.meta_rename.replace_in_file(_file, 'foo', 'goo')

    with open(_file, 'r') as f:
      source = f.read()

    safe_delete(_file)

    self.assertEqual(source, 'bar goo')

  def _prepare_dependencies(self):
    targets = {}

    targets['a'] = self.create_library('a', 'java_library', 'a', ['A.java'])
    targets['b'] = self.create_library('b', 'java_library', 'b', ['B.java'], dependencies=['a'])

    return targets.values()
