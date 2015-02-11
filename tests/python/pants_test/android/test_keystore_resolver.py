# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
import unittest
from contextlib import contextmanager

from pants.backend.android.keystore.keystore_resolver import KeystoreResolver
from pants.util.contextutil import temporary_file


class TestKeystoreResolver(unittest.TestCase):
  """Test KeyResolver class that creates Keystore objects from .ini config files."""

  @contextmanager
  def config_file(self,
                  build_type='debug',
                  keystore_location='%(homedir)s/.android/debug.keystore',
                  keystore_alias='androiddebugkey',
                  keystore_password='android',
                  key_password='android'):
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
        """
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
      for key in keystores:
        self.assertEquals(key.build_type, 'debug')

  def test_resolve_release(self):
    with self.config_file(build_type="release") as config:
      keystores = KeystoreResolver.resolve(config)
      for key in keystores:
        self.assertEquals(key.build_type, 'release')

  def test_resolve_mixed_case(self):
    with self.config_file(build_type="DeBuG") as config:
      keystores = KeystoreResolver.resolve(config)
      for key in keystores:
        self.assertEquals(key.build_type, 'debug')

  def test_bad_build_type(self):
    with self.config_file(build_type="bad-build-type") as config:
      keystores = KeystoreResolver.resolve(config)
      for key in keystores:
        with self.assertRaises(ValueError):
          key.build_type

  def test_set_location(self):
    with temporary_file() as temp_location:
      with self.config_file(keystore_location=temp_location.name) as config:
        keystores = KeystoreResolver.resolve(config)
        for key in keystores:
          self.assertEqual(key.keystore_location, temp_location.name)

  def test_expanding_path(self):
    with self.config_file(keystore_location="~/dir") as config:
      keystores = KeystoreResolver.resolve(config)
      for key in keystores:
        self.assertEqual(key.keystore_location, os.path.expandvars('~/dir'))

  def test_bad_config_location(self):
    with self.assertRaises(KeystoreResolver.Error):
        KeystoreResolver.resolve(os.path.join('no', 'config_file', 'here'))

  def test_a_missing_field(self):
    with self.assertRaises(KeystoreResolver.Error):
      with self.config_file(keystore_alias="") as config:
        KeystoreResolver.resolve(config)
