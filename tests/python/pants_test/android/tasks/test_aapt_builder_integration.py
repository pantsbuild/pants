# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from pants_test.android.android_integration_test import AndroidIntegrationTest


class AaptBuilderIntegrationTest(AndroidIntegrationTest):
  """Integration test for AaptBuilder, which builds an unsigned .apk"""

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  reqs = AndroidIntegrationTest.requirements(TOOLS)

  @pytest.mark.skipif('not AaptBuilderIntegrationTest.reqs',
                      reason='Android integration test requires tools {0!r} '
                             'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_check(self):
    self.assertEquals(True, True)