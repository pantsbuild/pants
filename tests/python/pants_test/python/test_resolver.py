# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pex.platforms import Platform

from pants.backend.python.resolver import get_platforms
from pants.base.config import Config
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
      self.config = Config.load(configpaths=[ini.name])

  def test_get_current_platform(self):
    expected_platforms = [Platform.current(), 'linux-x86_64']
    self.assertEqual(set(expected_platforms),
                     set(get_platforms(self.config.getlist('python-setup', 'platforms'))))
