# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.backend.jvm.tasks.jvm_compile.jvm_compile import CacheHitCallback
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch


class CacheHitCallbackTest(unittest.TestCase):
  def test_when_key_has_associated_directory_cleans_dir(self):
    with temporary_dir() as tmpdir:
      filename = os.path.join(tmpdir, 'deleted')
      touch(filename)

      key = 'some-key'
      cache_key_to_class_dir = {key: tmpdir}
      CacheHitCallback(cache_key_to_class_dir)(key)
      self.assertFalse(os.path.exists(filename))
