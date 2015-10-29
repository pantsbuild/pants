# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import unittest

from pants_test.android.android_integration_test import AndroidIntegrationTest


class AaptGenIntegrationTest(AndroidIntegrationTest):
  """Integration test for AaptGen

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  a particular aapt binary on disk. The TOOLS are the ones required by the target in 'test_aapt_gen'
  method. If you add a target, you may need to expand the TOOLS list and perhaps define new
  BUILD_TOOLS or TARGET_SDK class variables.
  """

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  tools = AndroidIntegrationTest.requirements(TOOLS)

  def aapt_gen_test(self, target):
    pants_run = self.run_pants(['gen', target])
    self.assert_success(pants_run)

  @unittest.skipUnless(tools, reason='Android integration test requires tools {0!r} '
                                     'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_aapt_gen(self):
    self.aapt_gen_test(AndroidIntegrationTest.TEST_TARGET)

  @unittest.skipUnless(tools, reason='Android integration test requires tools {0!r} '
                                     'and ANDROID_HOME set in path.'.format(TOOLS))
  # TODO(mateor) Write a testproject instead of using hello_with_library which may change.
  def test_android_library_dep(self):
    # Doing the work under a tempdir gives us a handle for the workdir and guarantees a clean build.
    with self.temporary_workdir() as workdir:
      spec = 'examples/src/android/hello_with_library:'
      pants_run = self.run_pants_with_workdir(['gen', '-ldebug', spec], workdir)
      self.assert_success(pants_run)

      # Make sure that the R.java was produced for the binary and its library dependency.
      lib_file = 'gen/aapt/21/org/pantsbuild/examples/example_library/R.java'
      apk_file = 'gen/aapt/21/org/pantsbuild/examples/hello_with_library/R.java'
      self.assertTrue(os.path.isfile(os.path.join(workdir, lib_file)))
      self.assertTrue(os.path.isfile(os.path.join(workdir, apk_file)))

      # Scrape debug statements.
      def find_aapt_blocks(lines):
        for line in lines:
          if re.search(r'Executing: .*?\baapt', line):
            yield line

      aapt_blocks = list(find_aapt_blocks(pants_run.stderr_data.split('\n')))

      # Pulling in google-play-services-v21 from the SDK brings in 20 .aar libraries of which only 6
      # have resources. Add 2 for android_binary and android_library targets = 8 total invocations.
      self.assertEquals(len(aapt_blocks), 8, 'Expected eight invocations of the aapt tool!'
                                             '(was :{})\n{}'.format(len(aapt_blocks),
                                                                    pants_run.stderr_data))

      # Check to make sure the resources are being passed in correct order (apk->libs).
      for line in aapt_blocks:
        apk = re.search(r'hello_with_library.*?\b', line)
        library = re.search(r'examples/src/android/example_library/AndroidManifest.*?\b', line)
        resource_dirs = re.findall(r'-S ([^\s]+)', line)

        if apk:
          # The order of resource directories should mirror the dependencies. The dependency order
          # is hello_with_library -> example_library -> gms-library.
          self.assertEqual(resource_dirs[0], 'examples/src/android/hello_with_library/main/res')
          self.assertEqual(resource_dirs[1], 'examples/src/android/example_library/res')
          self.assertEqual(len(resource_dirs), 8, 'Expected eight resource dirs to be included '
                                                   'when calling aapt on hello_with_library apk. '
                                                   '(was: {})\n'.format(len(resource_dirs)))
        elif library:
          # The seven invocations are the example_library and the 6 gms dependencies.
          self.assertEqual(len(resource_dirs), 7, 'Expected seven resource dir to be included '
                                                   'when calling aapt on example_library dep. '
                                                   '(was: {})\n'.format(len(resource_dirs)))
        else:
          self.assertEqual(len(resource_dirs), 1, 'Expected one resource dir to be included when '
                                                   'calling aapt on each gms-library dep. '
                                                   '(was: {})\n'.format(len(resource_dirs)))
