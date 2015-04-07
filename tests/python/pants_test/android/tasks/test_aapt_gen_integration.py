# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

import pytest

from pants.util.contextutil import temporary_dir
from pants_test.android.android_integration_test import AndroidIntegrationTest


class AaptGenIntegrationTest(AndroidIntegrationTest):
  """Integration test for AaptGen

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  a dx.jar anywhere on disk. The TOOLS are the ones required by the target in 'test_aapt_gen'
  method. If you add a target, you may need to expand the TOOLS list and perhaps define new
  BUILD_TOOLS or TARGET_SDK class variables.
  """

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  tools = AndroidIntegrationTest.requirements(TOOLS)

  @pytest.mark.skipif('not AaptGenIntegrationTest.tools',
                      reason='Android integration test requires tools {0!r} '
                             'and ANDROID_HOME set in path.'.format(TOOLS))

  def aapt_gen_test(self, target):
    pants_run = self.run_pants(['gen', target])
    self.assert_success(pants_run)

  def test_aapt_gen(self):
    self.aapt_gen_test(AndroidIntegrationTest.TEST_TARGET)

  def test_android_library_dep(self):
    # Doing the work under a tempdir gives us a handle for the workdir and guarantees a clean build.
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      spec = 'examples/src/android/hello_with_library/main:hello_with_library'
      pants_run = self.run_pants_with_workdir(['gen', '-ldebug', spec], workdir)
      self.assert_success(pants_run)

      # Make sure that the R.java was produced for the binary and its library dependency.
      lib_file = 'gen/aapt/19/org/pantsbuild/example/pants_library/R.java'
      apk_file = 'gen/aapt/19/org/pantsbuild/example_library/hello_with_library/R.java'
      self.assertEqual(os.path.isfile(os.path.join(workdir, lib_file)), True)
      self.assertEqual(os.path.isfile(os.path.join(workdir, apk_file)), True)

      # Scrape debug statements.
      def find_aapt_blocks(lines):
        for line in lines:
          if re.search(r'Executing: .*?\baapt', line):
            yield line

      aapt_blocks = list(find_aapt_blocks(pants_run.stderr_data.split('\n')))
      self.assertEquals(len(aapt_blocks), 2, 'Expected two invocations of the aapt tool!'
                                             '(was :{})\n{}'.format(len(aapt_blocks),
                                                                    pants_run.stderr_data))

      # Check to make sure the resources are being passed in correct order (apk->libs).
      for line in aapt_blocks:
        apk = re.search(r'hello_with_library.*?\b', line)
        if apk:
          resource_dirs = re.findall(r'-S ([^\s]+)', line)
          self.assertEqual(resource_dirs[0], 'examples/src/android/hello_with_library/main/res')
          self.assertEqual(resource_dirs[1], 'examples/src/android/example_library/res')
          self.assertEquals(len(resource_dirs), 2, 'Expected two resource dirs to be included '
                                                   'when calling aapt on hello_with_library apk. '
                                                   '(was: {})\n'.format(resource_dirs))
        else:
          # If the apk target name didn't match, we know it called aapt on the library dependency.
          resource_dirs = re.findall(r'-S.*?', line)
          self.assertEquals(len(resource_dirs), 1, 'Expected one resource dirs to be included when '
                                                   'calling aapt on dexample_library dep. '
                                                   '(was: {})\n'.format(resource_dirs))
