# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants_test.pants_run_integration_test import PantsRunIntegrationTest

from pex.pex_info import PexInfo


TARGET_TMPL = '''
python_binary(
  source='main.py',
  zip_safe={}
)
'''


class PythonBinaryIntegrationTest(PantsRunIntegrationTest):
  TEST_PROJECT = 'testprojects/src/python/cache_fields'
  TEST_BUILD = os.path.join(TEST_PROJECT, 'BUILD')
  TEST_PEX = 'dist/cache_fields.pex'
  ZIP_SAFE_TRUE_TARGET = TARGET_TMPL.format('True')
  ZIP_SAFE_FALSE_TARGET = TARGET_TMPL.format('False')

  def assert_pex_attribute(self, pex, attr, value):
    self.assertTrue(os.path.exists(pex))
    pex_info = PexInfo.from_pex(pex)
    self.assertEquals(getattr(pex_info, attr), value)

  @staticmethod
  @contextmanager
  def mutated_file(filename, content):
    with open(filename, 'rb') as fh:
      old_content = fh.read()

    with open(filename, 'wb') as fh:
      fh.write(content)

    try:
      yield
    finally:
      with open(filename, 'wb') as fh:
        fh.write(old_content)

  def test_zipsafe_caching(self):
    # Create a pex from a simple python_binary target and assert it has zip_safe=True (default).
    self.assert_success(self.run_pants(command=['binary', self.TEST_PROJECT]))
    self.assert_pex_attribute(self.TEST_PEX, 'zip_safe', True)

    # Mutate the target to set zip_safe=False and create/check the resulting pex.
    with self.mutated_file(self.TEST_BUILD, self.ZIP_SAFE_FALSE_TARGET):
      self.assert_success(self.run_pants(command=['binary', self.TEST_PROJECT]))
      self.assertTrue(os.path.exists(self.TEST_PEX))
      self.assert_pex_attribute(self.TEST_PEX, 'zip_safe', False)

    # Mutate the target to set zip_safe=True and create/check the resulting pex.
    with self.mutated_file(self.TEST_BUILD, self.ZIP_SAFE_TRUE_TARGET):
      self.assert_success(self.run_pants(command=['binary', self.TEST_PROJECT]))
      self.assertTrue(os.path.exists(self.TEST_PEX))
      self.assert_pex_attribute(self.TEST_PEX, 'zip_safe', True)
