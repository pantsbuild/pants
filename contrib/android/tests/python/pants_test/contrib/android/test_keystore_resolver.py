# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
import unittest
from contextlib import contextmanager

from pants.util.contextutil import temporary_file

from pants.contrib.android.keystore.keystore_resolver import KeystoreResolver


class TestKeystoreResolver(unittest.TestCase):
  """Test KeyResolver class that creates Keystore objects from .ini config files."""

  @contextmanager
  def config_file(self,
                  build_type='debug',
                  keystore_location='%(pants_configdir)s/android/debug.keystore',
                  keystore_alias='androiddebugkey',
                  keystore_password='android',
                  key_password='android'):
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
        """

        [test-release]

        build_type: release
        keystore_location: /some/path
        keystore_alias: test
        keystore_password: password
        key_password: password

        [default-debug]

        build_type: {0}
        keystore_location: {1}
        keystore_alias: {2}
        keystore_password: {3}
        key_password: {4}
        """).format(build_type, keystore_location, keystore_alias, keystore_password, key_password))
      path = fp.name
      fp.close()
      yield path

  def test_resolve(self):
    with self.config_file() as config:
      keystores = KeystoreResolver.resolve(config)
      self.assertEquals(keystores['default-debug'].build_type, 'debug')

  def test_resolve_release(self):
    with self.config_file() as config:
      keystores = KeystoreResolver.resolve(config)
      self.assertEquals(keystores['test-release'].build_type, 'release')

  def test_resolve_mixed_case(self):
    with self.config_file(build_type='ReleASE') as config:
      keystores = KeystoreResolver.resolve(config)
      self.assertEquals(keystores['test-release'].build_type, 'release')

  def test_bad_build_type(self):
    with self.config_file(build_type='bad-build-type') as config:
      keystores = KeystoreResolver.resolve(config)
      with self.assertRaises(ValueError):
        keystores['default-debug'].build_type

  def test_set_location(self):
    with temporary_file() as temp_location:
      with self.config_file(keystore_location=temp_location.name) as config:
        keystores = KeystoreResolver.resolve(config)
        self.assertEqual(keystores['default-debug'].keystore_location, temp_location.name)

  def test_expanding_key_path(self):
    with self.config_file(keystore_location='~/dir') as config:
      keystores = KeystoreResolver.resolve(config)
      self.assertEqual(keystores['default-debug'].keystore_location, os.path.expanduser('~/dir'))

  def test_bad_config_location(self):
    with self.assertRaises(KeystoreResolver.Error):
      KeystoreResolver.resolve(os.path.join('no', 'config_file', 'here'))

  def test_a_missing_field(self):
    with self.assertRaises(KeystoreResolver.Error):
      with self.config_file(keystore_alias="") as config:
        KeystoreResolver.resolve(config)
