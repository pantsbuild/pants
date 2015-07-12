# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.core.tasks import builddictionary, reflect
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.python.register import build_file_aliases as register_python
from pants_test.base_test import BaseTest


class ExtractedContentSanityTests(BaseTest):
  @property
  def alias_groups(self):
    return register_core().merge(register_jvm().merge(register_python()))

  def setUp(self):
    super(ExtractedContentSanityTests, self).setUp()
    self._syms = reflect.assemble_buildsyms(build_file_parser=self.build_file_parser)

  def test_sub_tocls(self):
    python_symbols = builddictionary.python_sub_tocl(self._syms).e

    # python_requirements goes through build_file_aliases.curry_context.
    # It's in the "Python" sub_tocl, but tenuously
    self.assertTrue('python_requirements' in python_symbols)

    # Some less-tenuous sanity checks
    for sym in ['python_library', 'python_tests']:
      self.assertTrue(sym in python_symbols)

    jvm_symbols = builddictionary.jvm_sub_tocl(self._syms).e
    for sym in ['java_library', 'scala_library']:
      self.assertTrue(sym in jvm_symbols)
