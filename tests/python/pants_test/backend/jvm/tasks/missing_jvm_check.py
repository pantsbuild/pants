# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.java.distribution.distribution import DistributionLocator
from pants_test.subsystem.subsystem_util import init_subsystem


def is_missing_jvm(version):
  init_subsystem(DistributionLocator)
  try:
    DistributionLocator.cached(minimum_version=version, maximum_version='{}.9999'.format(version))
    return False
  except DistributionLocator.Error:
    return True
