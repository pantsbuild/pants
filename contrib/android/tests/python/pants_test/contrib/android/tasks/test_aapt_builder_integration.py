# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import unittest

from pants_test.contrib.android.android_integration_test import AndroidIntegrationTest


class AaptBuilderIntegrationTest(AndroidIntegrationTest):
  """Integration test for AaptBuilder, which builds an unsigned .apk

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  an aapt binary anywhere on disk. The TOOLS are the ones required by the target in the
  'test_aapt_bundle' method. If you add a target, you may need to expand the TOOLS list
  and perhaps define new BUILD_TOOLS or TARGET_SDK class variables.
  """

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'lib', 'dx.jar'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  tools = AndroidIntegrationTest.requirements(TOOLS)

  @unittest.skipUnless(tools, reason='Android integration test requires tools {} '
                                 'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_aapt_bundle(self):
    self.bundle_test(AndroidIntegrationTest.TEST_TARGET)

  def bundle_test(self, target):
    pants_run = self.run_pants(['apk', target])
    self.assert_success(pants_run)

  @unittest.skipUnless(tools, reason='Android integration test requires tools {} '
                                     'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_android_library_products(self):
    # Doing the work under a tempdir gives us a handle for the workdir and guarantees a clean build.
    with self.temporary_workdir() as workdir:
      spec = 'contrib/android/examples/src/android/hello_with_library:'
      pants_run = self.run_pants_with_workdir(['apk', '-ldebug', spec], workdir)
      self.assert_success(pants_run)

      # Make sure that the unsigned apk was produced for the binary target.
      apk_file = 'apk/apk/org.pantsbuild.examples.hello_with_library.unsigned.apk'
      self.assertEqual(os.path.isfile(os.path.join(workdir, apk_file)), True)

      # Scrape debug statements.
      def find_aapt_blocks(lines):
        for line in lines:
          if re.search(r'Executing: .*?\baapt package -f -M', line):
            yield line

      aapt_blocks = list(find_aapt_blocks(pants_run.stderr_data.split('\n')))
      # Only one apk is built, so only one aapt invocation here, for any number of dependent libs.
      self.assertEquals(len(aapt_blocks), 1, 'Expected one invocation of the aapt tool! '
                                             '(was: {})\n{}'.format(len(aapt_blocks),
                                                                    pants_run.stderr_data))

      # Check to make sure the resources are being passed in correct order (apk->libs).
      for line in aapt_blocks:
        resource_dirs = re.findall(r'-S ([^\s]+)', line)
        self.assertEqual(resource_dirs[0], 'contrib/android/examples/src/android/hello_with_library/main/res')
        self.assertEqual(resource_dirs[1], 'contrib/android/examples/src/android/example_library/res')
        # The other six are google-play-services v21 resource_dirs. Their presence is enough.
        self.assertEquals(len(resource_dirs), 8, 'Expected eight resource dirs to be included '
                                                 'when calling aapt on hello_with_library apk.'
                                                 ' (was: {})\n'.format(resource_dirs))
