# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pkg_resources import WorkingSet

from pants.base.exceptions import BuildConfigurationError
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper


class OptionsInitializerTest(unittest.TestCase):
  def test_invalid_version(self):
    options_bootstrapper = OptionsBootstrapper(args=['--pants-version=99.99.9999'])
    initializer = OptionsInitializer(options_bootstrapper, WorkingSet())

    with self.assertRaises(BuildConfigurationError):
      initializer.setup()
