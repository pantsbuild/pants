# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pex.platforms import Platform

from pants.backend.python.python_chroot import PythonChroot


class PythonChrootTest(unittest.TestCase):
  def test_get_current_platform(self):
    expected_platforms = [Platform.current(), 'linux-x86_64']
    self.assertEqual(set(expected_platforms),
                     set(PythonChroot.get_platforms(['current', 'linux-x86_64'])))
