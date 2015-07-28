# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest

from pants_test.backend.jvm.tasks.jvm_compile.java.jvm_platform_integration_mixin import \
  JvmPlatformIntegrationMixin
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JavaCompileJvmPlatformIntegrationTest(JvmPlatformIntegrationMixin, PantsRunIntegrationTest):

  def get_pants_compile_args(self):
    return ['compile.java']

  @pytest.mark.xfail
  def test_compile_stale_platform_settings(self):
    super(JavaCompileJvmPlatformIntegrationTest, self).test_compile_stale_platform_settings()
