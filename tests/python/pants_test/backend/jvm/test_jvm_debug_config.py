# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.backend.jvm.jvm_debug_config import JvmDebugConfig
from pants_test.base.context_utils import create_config


class JvmDebugConfigTest(unittest.TestCase):
  def test_debug_config_default(self):
    config = create_config()
    self.assertEquals(5005, JvmDebugConfig.debug_port(config))
    self.assertEquals(['-Xdebug',
                       '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address=5005'],
                      JvmDebugConfig.debug_args(config))

  def test_debug_config_override(self):
    config = create_config(dedent("""
    [jvm]
    debug_port: 12345
    debug_args: ['foo', 'bar', 'port=%(debug_port)s']
    """))

    self.assertEquals(12345, JvmDebugConfig.debug_port(config))
    self.assertEquals(['foo', 'bar', 'port=12345'], JvmDebugConfig.debug_args(config))
