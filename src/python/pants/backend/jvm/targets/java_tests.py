# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.base.deprecated import warn_or_error


class JavaTests(JUnitTests):
  def __init__(self, *args, **kwargs):
    super(JavaTests, self).__init__(*args, **kwargs)
    warn_or_error('1.4.0',
                  'pants.backend.jvm.targets.java_tests.JavaTests',
                  'Use pants.backend.jvm.targets.junit_tests.JUnitTests instead.')
