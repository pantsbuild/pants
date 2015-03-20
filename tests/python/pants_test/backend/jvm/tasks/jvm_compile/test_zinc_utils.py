# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils
from pants_test.base_test import BaseTest


class TestZincUtils(BaseTest):

  def test_identify_zinc_jars(self):
    cp = ['/foo/bar/baz/compiler-interface-2.10.11-M1.jar',
          '/foo/bar/qux/sbt-interface-2.10.12-M2.jar']
    expected = {
      'compiler-interface': '/foo/bar/baz/compiler-interface-2.10.11-M1.jar',
      'sbt-interface': '/foo/bar/qux/sbt-interface-2.10.12-M2.jar'
    }
    self.assertEquals(expected, ZincUtils.identify_zinc_jars(cp))

  def test_classpath_relativization(self):
    jar_outside_build_root = os.path.join(os.path.sep, 'outside-build-root', 'bar.jar')
    classpath = [os.path.join(self.build_root, 'foo.jar'), jar_outside_build_root]
    relativized_classpath = ZincUtils.relativize_classpath(classpath)
    jar_relpath = os.path.relpath(jar_outside_build_root, self.build_root)
    self.assertEquals(['foo.jar', jar_relpath], relativized_classpath)
