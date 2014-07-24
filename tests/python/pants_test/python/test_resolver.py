# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from twitter.common.python.platforms import Platform

from pants.base.config import Config
from pants.backend.python.resolver import get_platforms
from pants.util.contextutil import temporary_file


class ResolverTest(unittest.TestCase):
  def setUp(self):
    with temporary_file() as ini:
      ini.write(
'''
[python-setup]
platforms: [
  'current',
  'linux-x86_64']
''')
      ini.close()
      self.config = Config.load(configpath=ini.name)

  def test_get_current_platform(self):
    expected_platforms = [Platform.current(), 'linux-x86_64']
    self.assertEqual(set(expected_platforms),
                     set(get_platforms(self.config.getlist('python-setup', 'platforms'))))
