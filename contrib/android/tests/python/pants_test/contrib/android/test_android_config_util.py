# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
import unittest

from pants.util.contextutil import temporary_file

from pants.contrib.android.android_config_util import AndroidConfigUtil


class TestAndroidConfigUtil(unittest.TestCase):
  """Test the AndroidConfigUtil class."""

  @classmethod
  def contents(cls):
    ini = textwrap.dedent(
      """
      # Android Keystore definitions. Follow this format when adding a keystore definition.
      # Each keystore has an arbitrary name and is required to have all five fields below.

      # These definitions can go anywhere in your file system, passed to pants as the option
      # '--keystore-config-location' in pants.ini or on the CLI.

      # The 'default-debug' definition is a well-known key installed along with the Android SDK.

      [default-debug]

      build_type: debug
      keystore_location: %(homedir)s/.android/debug.keystore
      keystore_alias: androiddebugkey
      keystore_password: android
      key_password: android
      """
    )
    return ini

  def test_setup_keystore_config(self):
    with temporary_file() as config:
      AndroidConfigUtil.setup_keystore_config(config.name)
      self.assertEquals(config.read(), self.contents())

  def test_no_permission_keystore_config(self):
    with temporary_file() as temp:
      os.chmod(temp.name, 0o400)
      with self.assertRaises(AndroidConfigUtil.AndroidConfigError):
        AndroidConfigUtil.setup_keystore_config(temp.name)
