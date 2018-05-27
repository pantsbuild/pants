# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot
from pants.engine.legacy.options_parsing import Options, OptionsParseRequest
from pants.init.engine_initializer import EngineInitializer
from pants_test.engine.util import init_native
from pants_test.test_base import TestBase


class TestEngineOptionsParsing(TestBase):

  # TODO: pants_test.engine.util.run_rule ?
  def test_options_parsing_request(self):
    products = self.scheduler.product_request(
      Options,
      [
        OptionsParseRequest.create(
          ['./pants', '-ldebug', 'binary', 'src/python::'],
          dict(PANTS_ENABLE_PANTSD='True', PANTS_BINARIES_BASEURLS='["https://bins.com"]')
        )
      ]
    )
    options = products[0].options
    self.assertIn('binary', options.goals)
    global_options = options.for_global_scope()
    self.assertEquals(global_options.level, 'debug')
    self.assertEquals(global_options.enable_pantsd, True)
    self.assertEquals(global_options.binaries_baseurls, ['https://bins.com'])
