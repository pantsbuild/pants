# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import unittest

from pants.contrib.rust.utils.basic_invocation_conversion_utils import (reduce_invocation,
                                                                        sanitize_crate_name)


test_invocation = {
  "package_name": "tar_api",
  "package_version": "0.0.1",
  "target_kind": [],
  "kind": "Host",
  "compile_mode": "build",
  "outputs": [],
  "links": {},
  "program": "rustc",
  "args": [],
  "env": {},
  "cwd": "/pants/src/rust/engine"
}


class UtilsTest(unittest.TestCase):
  def get_invocation(self):
    return copy.deepcopy(test_invocation)

  def test_reduce_invocation(self):
    invocation = self.get_invocation()
    result = {
      "package_name": "tar_api",
      "package_version": "0.0.1",
      "compile_mode": "build",
      "outputs": [],
      "links": {},
      "program": "rustc",
      "args": [],
      "env": {},
      "cwd": "/pants/src/rust/engine"
    }
    reduce_invocation(invocation)
    self.assertEqual(invocation, result)

  def test_sanitize_crate_name(self):
    self.assertEqual(sanitize_crate_name('tar-api-lib'), 'tar_api_lib')
