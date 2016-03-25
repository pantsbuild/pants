# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict

from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import ClasspathEntry, ClasspathProducts
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil, MissingClasspathEntryError
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

  def test_classpath_by_targets(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b],
                         excludes=[Exclude('com.example', 'lib')])

    classpath_products = ClasspathProducts(self.pants_workdir)

    path1 = self._path('jar/path1')
    path2 = self._path('jar/path2')
    path3 = os.path.join(self.pants_workdir, 'jar/path3')
    resolved_jar = ResolvedJar(M2Coordinate(org='com.example', name='lib', rev='1.0'),
                               cache_path='somewhere',
                               pants_path=path3)
    classpath_products.add_for_target(a, [('default', path1)])
    classpath_products.add_for_target(a, [('non-default', path2)])
    classpath_products.add_for_target(b, [('default', path2)])
    classpath_products.add_jars_for_targets([b], 'default', [resolved_jar])
    classpath_products.add_excludes_for_targets([a])

    # (a, path2) filtered because of conf
    # (b, path3) filtered because of excludes
    self.assertEquals(OrderedDict([(a, [ClasspathEntry(path1)]),
                                   (b, [ClasspathEntry(path2)])]),
                      ClasspathUtil.classpath_by_targets(a.closure(bfs=True),
                                                         classpath_products))

  def test_create_canonical_classpath(self):
    a = self.make_target('a/b', JvmTarget)

    jar_path = 'ivy/jars/org.x/lib/x-1.0.jar'
    classpath_products = ClasspathProducts(self.pants_workdir)

    resolved_jar = ResolvedJar(M2Coordinate(org='org', name='x', rev='1.0'),
                               cache_path='somewhere',
                               pants_path=self._path(jar_path))

    classpath_products.add_for_target(a, [('default', self._path('a.jar')),
                                          ('default', self._path('resources'))])
    classpath_products.add_jars_for_targets([a], 'default', [resolved_jar])

    with temporary_dir() as base_dir:
      self._test_canonical_classpath_helper(classpath_products,
                                            [a],
                                            base_dir,
                                            [
                                              'a.b.b-0.jar',
                                              'a.b.b-1',
                                              'a.b.b-2.jar',
                                            ],
                                            {
                                              'a.b.b-classpath.txt':
                                              '{}/a.jar:{}/resources:{}/{}\n'
                                               .format(self.pants_workdir, self.pants_workdir,
                                                       self.pants_workdir, jar_path)
                                            },
                                            excludes=set([Exclude(org='org', name='y')]))

    # incrementally delete the resource dendendency
    classpath_products = ClasspathProducts(self.pants_workdir)
    classpath_products.add_for_target(a, [('default', self._path('a.jar'))])
    self._test_canonical_classpath_helper(classpath_products,
                                          [a],
                                          base_dir,
                                          [
                                            'a.b.b-0.jar',
                                          ],
                                          {
                                            'a.b.b-classpath.txt':
                                            '{}/a.jar\n'.format(self.pants_workdir)
                                          })

    # incrementally add another jar dependency
    classpath_products = ClasspathProducts(self.pants_workdir)
    classpath_products.add_for_target(a, [('default', self._path('a.jar')),
                                          ('default', self._path('b.jar'))])
    self._test_canonical_classpath_helper(classpath_products,
                                          [a],
                                          base_dir,
                                          [
                                            'a.b.b-0.jar',
                                            'a.b.b-1.jar'
                                          ],
                                          {
                                            'a.b.b-classpath.txt':
                                            '{}/a.jar:{}/b.jar\n'.format(self.pants_workdir,
                                                                         self.pants_workdir)
                                          })

  def test_create_canonical_classpath_with_broken_classpath(self):
    """Test exception is thrown when the jar file is missing."""

    a = self.make_target('a/b', JvmTarget)
    classpath_products = ClasspathProducts(self.pants_workdir)
    jar_path = 'ivy/jars/org.x/lib/x-1.0.jar'

    # this sets the path for the artifact without actually materializing it.
    resolved_jar = ResolvedJar(M2Coordinate(org='org', name='x', rev='1.0'),
                               cache_path='somewhere',
                               pants_path=os.path.join(self.pants_workdir, jar_path))
    classpath_products.add_jars_for_targets([a], 'default', [resolved_jar])

    with temporary_dir() as base_dir:
      with self.assertRaises(MissingClasspathEntryError):
        self._test_canonical_classpath_helper(classpath_products,
                                              [a],
                                              base_dir,
                                              [],
                                              {})

  def test_create_canonical_classpath_no_duplicate_entry(self):
    """Test no more than one symlink are created for the same classpath entry."""
    jar_path = 'ivy/jars/org.x/lib/x-1.0.jar'
    resolved_jar = ResolvedJar(M2Coordinate(org='org', name='x', rev='1.0'),
                               cache_path='somewhere',
                               pants_path=self._path(jar_path))
    target_a = self.make_target('a', JvmTarget)
    target_b = self.make_target('b', JvmTarget)

    classpath_products = ClasspathProducts(self.pants_workdir)
    # Both target a and target b depend on the same jar library
    classpath_products.add_jars_for_targets([target_a], 'default', [resolved_jar])
    classpath_products.add_jars_for_targets([target_b], 'default', [resolved_jar])

    with temporary_dir() as base_dir:
      # Only target a generates symlink to jar library, target b skips creating the
      # symlink for the same jar library. Both targets' classpath.txt files should
      # still contain the jar library.
      self._test_canonical_classpath_helper(classpath_products,
                                            [target_a, target_b],
                                            base_dir,
                                            ['a.a-0.jar'],
                                            {
                                              'a.a-classpath.txt':
                                                '{}/{}\n'.format(self.pants_workdir, jar_path),
                                              'b.b-classpath.txt':
                                                '{}/{}\n'.format(self.pants_workdir, jar_path),
                                            })

  def _test_canonical_classpath_helper(self,
                                       classpath_products,
                                       targets,
                                       libs_dir,
                                       expected_canonical_classpath,
                                       expected_classspath_files,
                                       excludes=None):
    """
    Helper method to call `create_canonical_classpath` and verify generated canonical classpath.

    :param ClasspathProducts classpath_products: Classpath products.
    :param list targets: List of targets to generate canonical classpath from.
    :param string libs_dir: Directory where canonical classpath are to be generated.
    :param list expected_canonical_classpath: List of canonical classpath relative to a base directory.
    :param dict expected_classspath_files: A dict of classpath.txt path to its expected content.
    """
    canonical_classpath = ClasspathUtil.create_canonical_classpath(classpath_products,
                                                                   targets,
                                                                   libs_dir,
                                                                   save_classpath_file=True,
                                                                   internal_classpath_only=False,
                                                                   excludes=excludes)
    # check canonical path returned
    self.assertEquals(expected_canonical_classpath,
                      relativize_paths(canonical_classpath, libs_dir))

    # check canonical path created contain the exact set of files, no more, no less
    self.assertTrue(contains_exact_files(libs_dir,
                                         expected_canonical_classpath +
                                         expected_classspath_files.keys()))

    # check the content of classpath.txt
    for classpath_file in expected_classspath_files:
      self.assertTrue(check_file_content(os.path.join(libs_dir, classpath_file),
                                         expected_classspath_files[classpath_file]))

  def _path(self, p):
    return self.create_workdir_file(p)
