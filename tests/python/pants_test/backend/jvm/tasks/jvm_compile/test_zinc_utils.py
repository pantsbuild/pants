# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from mock import patch
import os

from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils
from pants.base.build_environment import get_buildroot
from pants_test.base_test import BaseTest


class TestZincUtils(BaseTest):

  def test_get_compile_args(self):
    classpath = [os.path.join(get_buildroot(), 'foo.jar'),
                 '/outside-build-root/bar.jar']
    sources = ['X.scala']

    args = ZincUtils. _get_compile_args([], classpath, sources, 'bogus output dir',
                                        'bogus analysis file', [])
    classpath_found = False
    for arg in args:
      if classpath_found:
        self.assertEquals('foo.jar:/outside-build-root/bar.jar', arg)
        break
      if arg == '-classpath':
        classpath_found = True
