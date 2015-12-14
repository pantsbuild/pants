# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants_test.android.android_integration_test import AndroidIntegrationTest


class UnpackLibrariesIntegrationTest(AndroidIntegrationTest):
  """Integration test for UnpackLibraries."""

  # No android tools are needed but ANDROID_HOME needs to be set so we can fetch libraries from SDK.
  TOOLS = []
  tools = AndroidIntegrationTest.requirements(TOOLS)

  @unittest.skipUnless(tools, reason='UnpackLibraries integration test requires that '
                                     'ANDROID_HOME is set.')
  def test_library_unpack(self):
    with self.temporary_workdir() as workdir:
      spec = 'examples/src/android/hello_with_library:'
      pants_run = self.run_pants_with_workdir(['unpack-jars', spec], workdir)
      self.assert_success(pants_run)

      # Look for the unpacked aar contents.
      unpack_aar = 'unpack-jars/unpack-libs/com.android.support-support-v4-22.0.0.aar'
      # Look for unpacked classes.jar.
      unpack_jar = 'unpack-jars/unpack-libs/explode-jars/com.android.support-support-v4-22.0.0.aar'
      self.assertTrue(os.path.isdir(os.path.join(workdir, unpack_aar)))
      self.assertTrue(os.path.isdir(os.path.join(workdir, unpack_jar)))
