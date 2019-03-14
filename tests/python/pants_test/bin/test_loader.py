# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
import unittest
from builtins import map, str

import mock

from pants.bin.pants_loader import PantsLoader


class LoaderTest(unittest.TestCase):

  def test_is_supported_interpreter(self):
    unsupported_versions = {(2, 6), (3, 3), (3, 4), (3, 5), (4, 0)}
    supported_versions = {(2, 7), (3, 6), (3, 7), (3, 8)}
    self.assertTrue(all(not PantsLoader.is_supported_interpreter(major, minor) for major, minor in unsupported_versions))
    self.assertTrue(all(PantsLoader.is_supported_interpreter(major, minor) for major, minor in supported_versions))

  def test_ensure_valid_interpreter(self):
    current_interpreter_version = '.'.join(map(str, sys.version_info[0:2]))
    bypass_env = PantsLoader.INTERPRETER_IGNORE_ENV_VAR
    with mock.patch.object(PantsLoader, 'is_supported_interpreter', return_value=False):
      with self.assertRaises(PantsLoader.InvalidInterpreter) as e:
        PantsLoader.ensure_valid_interpreter()
      self.assertIn(current_interpreter_version, str(e.exception))
      self.assertIn(bypass_env, str(e.exception))
      with mock.patch.dict(os.environ, {bypass_env: "1"}):
        PantsLoader.ensure_valid_interpreter()
