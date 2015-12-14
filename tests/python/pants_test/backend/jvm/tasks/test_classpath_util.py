# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.goal.products import UnionProducts
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import relativize_paths
from pants_test.base_test import BaseTest
from pants_test.testutils.file_test_util import check_file_content, contains_exact_files


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

  def test_create_canonical_classpath(self):
    a = self.make_target('a/b', JvmTarget)

    classpath_products = ClasspathProducts(self.pants_workdir)

    classpath_products.add_for_target(a, [('default', self._path('a.jar')),
                                          ('default', self._path('resources'))])

    self._test_canonical_classpath_helper(classpath_products, [a],
                                          [
                                            'a.b.b/0-a.jar',
                                            'a.b.b/1-resources'
                                          ],
                                          {
                                            'a.b.b/classpath.txt':
                                              '{}/a.jar:{}/resources\n'.format(self.pants_workdir,
                                                                               self.pants_workdir)
                                           },
                                          True)

  def test_create_canonical_classpath_with_common_prefix(self):
    """
    A special case when two targets' canonical classpath share a common prefix.

    Until we use `target.id` for canonical classpath, today's implementation is error-prone.
    This is such a regression test case added for a bug discovered in
    https://github.com/pantsbuild/pants/pull/2664

    TODO(peiyu) Remove once we fully migrate to use `target.id`.
    """
    # a and c' canonical classpath share a common prefix: a/b/b
    a = self.make_target('a/b', JvmTarget)
    c = self.make_target('a/b/b/c', JvmTarget)

    classpath_products = ClasspathProducts(self.pants_workdir)

    classpath_products.add_for_target(a, [('default', self._path('a.jar'))])
    classpath_products.add_for_target(c, [('default', self._path('c.jar'))])

    # target c first to verify its first created canonical classpath is preserved
    self._test_canonical_classpath_helper(classpath_products, [c, a],
                                          [
                                            'a/b/b/c/c/0-c.jar',
                                            'a/b/b/0-a.jar',
                                          ],
                                          {
                                            'a/b/b/classpath.txt':
                                              '{}/a.jar\n'.format(self.pants_workdir),
                                            'a/b/b/c/c/classpath.txt':
                                              '{}/c.jar\n'.format(self.pants_workdir),
                                          },
                                          False)

  def _test_canonical_classpath_helper(self, classpath_products, targets,
                                       expected_canonical_classpath,
                                       expected_classspath_files,
                                       use_target_id):
    """
    Helper method to call `create_canonical_classpath` and verify generated canonical classpath.

    :param ClasspathProducts classpath_products: Classpath products.
    :param list targets: List of targets to generate canonical classpath from.
    :param list expected_canonical_classpath: List of canonical classpath relative to a base directory.
    :param dict expected_classspath_files: A dict of classpath.txt path to its expected content.
    """
    with temporary_dir() as base_dir:
      canonical_classpath = ClasspathUtil.create_canonical_classpath(classpath_products,
                                                                     targets,
                                                                     base_dir,
                                                                     save_classpath_file=True,
                                                                     use_target_id=use_target_id)
      # check canonical path returned
      self.assertEquals(expected_canonical_classpath,
                        relativize_paths(canonical_classpath, base_dir))

      # check canonical path created contain the exact set of files, no more, no less
      self.assertTrue(contains_exact_files(base_dir,
                                           expected_canonical_classpath +
                                           expected_classspath_files.keys()))

      # check the content of classpath.txt
      for classpath_file in expected_classspath_files:
        self.assertTrue(check_file_content(os.path.join(base_dir, classpath_file),
                                           expected_classspath_files[classpath_file]))

  def _path(self, p):
    return os.path.join(self.pants_workdir, p)
