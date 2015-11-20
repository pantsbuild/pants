# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.goal.products import UnionProducts
from pants_test.base_test import BaseTest


class ClasspathUtilTest(BaseTest):

  def test_path_with_differing_conf_ignored(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = UnionProducts()

    path = os.path.join(self.build_root, 'jar/path')
    classpath_product.add_for_target(a, [('default', path)])

    classpath = ClasspathUtil.compute_classpath([a],
                                                classpath_product,
                                                extra_classpath_tuples=[],
                                                confs=['not-default'])

    self.assertEqual([], classpath)

  def test_path_with_overlapped_conf_added(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = UnionProducts()

    path = os.path.join(self.build_root, 'jar/path')
    classpath_product.add_for_target(a, [('default', path)])

    classpath = ClasspathUtil.compute_classpath([a],
                                                classpath_product,
                                                extra_classpath_tuples=[],
                                                confs=['not-default', 'default'])

    self.assertEqual([path], classpath)

  def test_extra_path_added(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = UnionProducts()

    path = os.path.join(self.build_root, 'jar/path')
    classpath_product.add_for_target(a, [('default', path)])

    extra_path = 'new-path'
    extra_cp_tuples = [('default', extra_path)]
    classpath = ClasspathUtil.compute_classpath([a],
                                                classpath_product,
                                                extra_classpath_tuples=extra_cp_tuples,
                                                confs=['default'])

    self.assertEqual([path, extra_path], classpath)

  def test_relies_on_product_to_validate_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = UnionProducts()
    classpath_product.add_for_target(a, [('default', '/dev/null')])

    classpath = ClasspathUtil.compute_classpath([a],
                                                classpath_product,
                                                extra_classpath_tuples=[],
                                                confs=['default'])

    self.assertEqual(['/dev/null'], classpath)
