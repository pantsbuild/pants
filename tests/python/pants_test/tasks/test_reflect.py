# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.core.tasks import reflect
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.python.register import build_file_aliases as register_python
from pants_test.base_test import BaseTest


class BuildsymsSanityTests(BaseTest):
  @property
  def alias_groups(self):
    return register_core().merge(register_jvm().merge(register_python()))

  def setUp(self):
    super(BuildsymsSanityTests, self).setUp()
    self._syms = reflect.assemble_buildsyms(build_file_parser=self.build_file_parser)

  def test_exclude_unuseful(self):
    # These symbols snuck into old dictionaries, make sure they don't again:
    for unexpected in ['__builtins__', 'Target']:
      self.assertTrue(unexpected not in self._syms.keys(), 'Found %s' % unexpected)

  def test_java_library(self):
    # Good bet that 'java_library' exists and contains these text blobs
    jl_text = '{0}'.format(self._syms['java_library']['defn'])
    self.assertIn('java_library', jl_text)
    self.assertIn('dependencies', jl_text)
    self.assertIn('sources', jl_text)
