# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.java.jar.manifest import Manifest


class TestManifest(unittest.TestCase):

  def test_isempty(self):
    manifest = Manifest()
    self.assertTrue(manifest.is_empty())
    manifest.addentry('Header', 'value')
    self.assertFalse(manifest.is_empty())

  def test_addentry(self):
    manifest = Manifest()
    manifest.addentry('Header', 'value')
    self.assertEquals(
      'Header: value\n', manifest.contents())

  def test_too_long_entry(self):
    manifest = Manifest()
    with self.assertRaises(ValueError):
      manifest.addentry(
        '1234567890123456789012345678901234567890'
        '12345678901234567890123456789', 'value')

  def test_nonascii_char(self):
    manifest = Manifest()
    with self.assertRaises(UnicodeEncodeError):
      manifest.addentry('X-Copyright', '© 2015')
