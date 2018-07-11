# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest

from pants.base.exceptions import BuildConfigurationError
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper


class OptionsInitializerTest(unittest.TestCase):
  def test_invalid_version(self):
    options_bootstrapper = OptionsBootstrapper(args=['--pants-version=99.99.9999'])
    build_config = BuildConfigInitializer(options_bootstrapper)

    with self.assertRaises(BuildConfigurationError):
      OptionsInitializer.create(options_bootstrapper, build_config)
