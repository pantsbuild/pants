# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.backend.native.utils.platform_utils import platform_specific


class NativeToolchainIntegration(PantsRunIntegrationTest):

  native_subsystems_test_target = 'tests/python/pants_test/backend/native/subsystems:subsystems'

  @platform_specific('linux')
  def test_hello_c_no_libc(self):
    cmd = ['test', self.native_subsystems_test_target]
    pants_make_executable_test = self.run_pants(command=cmd, config={
      'native-toolchain': {
        'enable_libc_search': False,
      }
    })

    self.assert_failure(pants_make_executable_test)

    self.assertEqual("crti.o", pants_make_executable_test.stdout_data)
