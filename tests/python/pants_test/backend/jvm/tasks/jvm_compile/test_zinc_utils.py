# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils
from pants_test.base_test import BaseTest


class TestZincUtils(BaseTest):

  def test_get_compile_args(self):
    jar_outside_build_root = os.path.join(os.path.sep, 'outside-build-root', 'bar.jar')
    classpath = [os.path.join(self.build_root, 'foo.jar'), jar_outside_build_root]
    sources = ['X.scala']

    args = ZincUtils._get_compile_args([], classpath, sources, 'bogus output dir',
                                        'bogus analysis file', [])
    classpath_found = False
    classpath_correct = False
    for arg in args:
      if classpath_found:
        # Classpath elements are always relative to the build root.
        jar_relpath = os.path.relpath(jar_outside_build_root, self.build_root)
        self.assertEquals('foo.jar:{0}'.format(jar_relpath), arg)
        classpath_correct = True
        break
      if arg == '-classpath':
        classpath_found = True
    self.assertTrue(classpath_correct)
