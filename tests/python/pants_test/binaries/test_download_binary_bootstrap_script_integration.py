# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import unittest

from pants.base.build_environment import get_buildroot
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class BinaryUtilIntegrationTest(unittest.TestCase):

  script_path = os.path.join(
    get_buildroot(),
    'build-support/bin/download_binary.sh',
  )

  def test_fetch_cmake_success(self):
    self.assertEqual(
      0,
      subprocess.check_call([self.script_path, 'cmake', '3.9.5']))

  def test_fetch_nonexistent_tool_failure(self):
    try:
      subprocess.check_output([self.script_path, 'cmake', '213521351235'],
                              stderr=subprocess.STDOUT)
      self.fail('Version 213521351235 of cmake should not exist!')
    except subprocess.CalledProcessError as e:
      self.assertNotEqual(0, e.returncode)
      self.assertIn('Failed to fetch cmake binary from any source', e.output)
