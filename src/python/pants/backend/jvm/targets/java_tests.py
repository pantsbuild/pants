# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.junit_tests import DeprecatedJavaTestsAlias
from pants.base.deprecated import warn_or_error


# Warn if any code imports this module.
# There's a separate deprecation warning in register.py for targets that use the old alias.
warn_or_error('1.4.0.dev0',
              'pants.backend.jvm.targets.java_tests.JavaTests',
              'Use pants.backend.jvm.targets.junit_tests.JUnitTests instead.')

JavaTests = DeprecatedJavaTestsAlias
