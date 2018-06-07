# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.engine.legacy.options_parsing import Options, OptionsParseRequest, parse_options
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants_test.engine.util import run_rule


class TestEngineOptionsParsing(unittest.TestCase):

  def test_options_parsing_request(self):
    parse_request = OptionsParseRequest.create(
      ['./pants', '-ldebug', '--python-setup-wheel-version=3.13.37', 'binary', 'src/python::'],
      dict(PANTS_ENABLE_PANTSD='True', PANTS_BINARIES_BASEURLS='["https://bins.com"]')
    )

    # TODO: Once we have the ability to get FileContent for arbitrary
    # paths outside of the buildroot, we can move the construction of
    # OptionsBootstrapper into an @rule by cooperatively calling
    # OptionsBootstrapper.produce_and_set_bootstrap_options() which
    # will yield lists of file paths for use as subject values and permit
    # us to avoid the direct file I/O that this currently requires.
    options_bootstrapper = OptionsBootstrapper.from_options_parse_request(parse_request)
    build_config = BuildConfigInitializer.get(options_bootstrapper)

    options = run_rule(parse_options, options_bootstrapper, build_config)[0]

    self.assertIn('binary', options.goals)
    global_options = options.for_global_scope()
    self.assertEquals(global_options.level, 'debug')
    self.assertEquals(global_options.enable_pantsd, True)
    self.assertEquals(global_options.binaries_baseurls, ['https://bins.com'])

    python_setup_options = options.for_scope('python-setup')
    self.assertEquals(python_setup_options.wheel_version, '3.13.37')
