# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JavaTestsTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'junit_tests': JavaTests,
      },
      context_aware_object_factories={
        'globs': Globs,
      },
    )

  def test_none(self):
    self.add_to_build_file('default', '''junit_tests(name='default', sources=None)''')
    with self.assertRaises(TargetDefinitionException):
      self.build_file_parser.scan(self.build_root)

  def test_empty_list(self):
    self.add_to_build_file('default', '''junit_tests(name='default', sources=[])''')
    with self.assertRaises(TargetDefinitionException):
      self.build_file_parser.scan(self.build_root)

  def test_empty_glob(self):
    self.add_to_build_file('default', '''junit_tests(name='default', sources=globs('nothing'))''')
    with self.assertRaises(TargetDefinitionException):
      self.build_file_parser.scan(self.build_root)
