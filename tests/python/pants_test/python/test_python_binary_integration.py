# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
from contextlib import contextmanager

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest

from pex.pex_info import PexInfo


TEST_PROJECT = 'testprojects/src/python/cache_fields'
TEST_BUILD = os.path.join(TEST_PROJECT, 'BUILD')
TEST_PEX = 'dist/cache_fields.pex'
ZIPSAFE_TARGET_TMPL = '''
python_binary(
  source='main.py',
  zip_safe={}
)
'''


class PythonBinaryIntegrationTest(PantsRunIntegrationTest):
  @staticmethod
  @contextmanager
  def caching_config():
    """Creates a temporary directory and returns a pants configuration for passing to pants_run."""
    with temporary_dir() as tmp_dir:
      yield {
        'cache': {
          'read': True,
          'write': True,
          'read_from': [tmp_dir],
          'write_to': [tmp_dir]
        }
      }

  @staticmethod
  @contextmanager
  def mutated_file(filename, content):
    """Temporarily mutates a file to simulate user edits."""
    with open(filename, 'rb') as fh:
      old_content = fh.read()

    with open(filename, 'wb') as fh:
      fh.write(content)

    try:
      yield
    finally:
      with open(filename, 'wb') as fh:
        fh.write(old_content)

  def assert_pex_attribute(self, pex, attr, value):
    self.assertTrue(os.path.exists(pex))
    pex_info = PexInfo.from_pex(pex)
    self.assertEquals(getattr(pex_info, attr), value)

  def test_zipsafe_caching(self):
    with self.caching_config() as pants_ini_config:
      build = functools.partial(
        self.run_pants,
        command=['binary', TEST_PROJECT],
        config=pants_ini_config
      )

      # Create a pex from a simple python_binary target and assert it has zip_safe=True (default).
      self.assert_success(build())
      self.assert_pex_attribute(TEST_PEX, 'zip_safe', True)

      # Simulate a user edit by adding zip_safe=False to the target and check the resulting pex.
      with self.mutated_file(TEST_BUILD, ZIPSAFE_TARGET_TMPL.format('False')):
        self.assert_success(build())
        self.assert_pex_attribute(TEST_PEX, 'zip_safe', False)

      # Simulate a user edit by adding zip_safe=True to the target and check the resulting pex.
      with self.mutated_file(TEST_BUILD, ZIPSAFE_TARGET_TMPL.format('True')):
        self.assert_success(build())
        self.assert_pex_attribute(TEST_PEX, 'zip_safe', True)
