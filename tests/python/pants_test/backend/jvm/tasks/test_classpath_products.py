# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import (ArtifactClasspathEntry, ClasspathEntry,
                                                        ClasspathProducts,
                                                        MissingClasspathEntryError)
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import relativize_paths
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.testutils.file_test_util import check_file_content, contains_exact_files


def resolved_example_jar_at(path, org='com.example', name='lib'):
  return ResolvedJar(M2Coordinate(org=org, name=name),
                     cache_path=os.path.join('resolver-cache-dir', path),
                     pants_path=path)


class ClasspathProductsTest(BaseTest):
  def setUp(self):
    super(ClasspathProductsTest, self).setUp()
    init_subsystem(Target.Arguments)

  def test_single_classpath_element_no_excludes(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts(self.pants_workdir)
    path = self.path('jar/path')
    self.add_jar_classpath_element_for_path(classpath_product, a, path)

    self.assertEqual([('default', path)], classpath_product.get_for_target(a))

  def test_copy(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    resolved_jar = self.add_jar_classpath_element_for_path(classpath_product,
                                                           a,
                                                           self._example_jar_path())
    classpath_product.add_for_target(a, [('default', self.path('a/path'))])

    copied = classpath_product.copy()

    a_closure = a.closure(bfs=True)

    self.assertEqual([('default', resolved_jar.pants_path), ('default', self.path('a/path'))],
                     classpath_product.get_for_targets(a_closure))
    self.assertEqual([('default', resolved_jar.pants_path), ('default', self.path('a/path'))],
                     copied.get_for_targets(a_closure))

    self.add_excludes_for_targets(copied, b, a)
    self.assertEqual([('default', resolved_jar.pants_path), ('default', self.path('a/path'))],
                     classpath_product.get_for_targets(a_closure))
    self.assertEqual([('default', self.path('a/path'))],
                     copied.get_for_targets(a_closure))

    copied.add_for_target(b, [('default', self.path('b/path'))])
    self.assertEqual([('default', resolved_jar.pants_path), ('default', self.path('a/path'))],
                     classpath_product.get_for_targets(a_closure))
    self.assertEqual([('default', self.path('a/path')), ('default', self.path('b/path'))],
                     copied.get_for_targets(a_closure))

  def test_fails_if_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts(self.pants_workdir)
    with self.assertRaises(TaskError) as cm:
      classpath_product.add_for_target(a, [('default', '/dev/null')])

    self.assertEqual(
      'Classpath entry /dev/null for target a:a is located outside the working directory "{}".'.format(self.pants_workdir),
      str(cm.exception))

  def test_fails_if_jar_paths_outside_buildroot(self):
    a = self.make_target('a', JvmTarget)

    classpath_product = ClasspathProducts(self.pants_workdir)
    with self.assertRaises(TaskError) as cm:
      classpath_product.add_jars_for_targets([a], 'default', [(resolved_example_jar_at('/dev/null'))])

    self.assertEqual(
      'Classpath entry /dev/null for target a:a is located outside the working directory "{}".'.format(self.pants_workdir),
      str(cm.exception))

  def test_excluded_classpath_element(self):
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_transitive_dependencies_excluded_classpath_element(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_jar_classpath_element_for_path(classpath_product, a, self._example_jar_path())
    self.add_excludes_for_targets(classpath_product, b, a)

    classpath = classpath_product.get_for_target(a)
    self.assertEqual([], classpath)

  def test_intransitive_dependencies_excluded_classpath_element(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    classpath_product.add_for_target(a, [('default', example_jar_path)])
    classpath_product.add_excludes_for_targets([a, b])

    intransitive_classpath = classpath_product.get_for_target(a)
    self.assertEqual([('default', example_jar_path)], intransitive_classpath)

  def test_parent_exclude_excludes_dependency_jar(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    self.add_jar_classpath_element_for_path(classpath_product, b, example_jar_path)
    self.add_excludes_for_targets(classpath_product, b, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_exclude_leaves_other_jars_unaffected(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    com_example_jar_path = self._example_jar_path()
    org_example_jar_path = self.path('ivy/jars/org.example/lib/123.4.jar')
    classpath_product.add_jars_for_targets([a], 'default',
                                          [resolved_example_jar_at(com_example_jar_path),
                                           resolved_example_jar_at(org_example_jar_path,
                                                                   org='org.example')])
    self.add_excludes_for_targets(classpath_product, b)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([('default', org_example_jar_path)], classpath)

  def test_parent_excludes_ignored_for_resolving_child_target(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b], excludes=[Exclude('com.example', 'lib')])

    example_jar_path = self._example_jar_path()
    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_jar_classpath_element_for_path(classpath_product, b, example_jar_path)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(b)

    self.assertEqual([('default', example_jar_path)], classpath)

  def test_excludes_used_across_targets(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_example_jar_classpath_element_for(classpath_product, b)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_excludes_similar_org_name(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.exam')], dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_example_jar_classpath_element_for(classpath_product, b)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_targets(a.closure(bfs=True))

    self.assertEqual([('default', self._example_jar_path())], classpath)

  def test_excludes_org_name(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example')], dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_example_jar_classpath_element_for(classpath_product, b)
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_target(a)

    self.assertEqual([], classpath)

  def test_jar_provided_by_transitive_target_excluded(self):
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example', 'lib', Repository()))
    consumer = self.make_target('consumer', JvmTarget)
    root = self.make_target('root', JvmTarget, dependencies=[provider, consumer])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_example_jar_classpath_element_for(classpath_product, consumer)
    self.add_excludes_for_targets(classpath_product, consumer, provider, root)

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([], classpath)

  def test_jar_provided_exclude_with_similar_name(self):
    # note exclude 'jars/com.example/l' should not match jars/com.example/lib/jars/123.4.jar
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example', 'li', Repository()))
    root = self.make_target('root', JvmTarget, dependencies=[provider])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_example_jar_classpath_element_for(classpath_product, root)
    self.add_excludes_for_targets(classpath_product, provider, root)

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([('default', self._example_jar_path())], classpath)

  def test_jar_provided_exclude_with_similar_org(self):
    provider = self.make_target('provider', ExportableJvmLibrary,
                         provides=Artifact('com.example.lib', '', Repository()))
    root = self.make_target('root', JvmTarget, dependencies=[provider])

    classpath_product = ClasspathProducts(self.pants_workdir)
    self.add_example_jar_classpath_element_for(classpath_product, root)
    self.add_excludes_for_targets(classpath_product, provider, root)

    classpath = classpath_product.get_for_target(root)

    self.assertEqual([('default', self._example_jar_path())], classpath)

  def test_jar_in_classpath_not_a_resolved_jar_ignored_by_excludes(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example')], dependencies=[b])

    example_jar_path = self._example_jar_path()

    classpath_product = ClasspathProducts(self.pants_workdir)
    classpath_product.add_for_target(b, [('default', example_jar_path)])
    self.add_excludes_for_targets(classpath_product, a)

    classpath = classpath_product.get_for_targets(a.closure(bfs=True))

    self.assertEqual([('default', example_jar_path)], classpath)

  def test_jar_missing_pants_path_fails_adding(self):
    b = self.make_target('b', JvmTarget)

    classpath_products = ClasspathProducts(self.pants_workdir)
    with self.assertRaises(TaskError) as cm:
      classpath_products.add_jars_for_targets([b], 'default',
                                              [ResolvedJar(M2Coordinate(org='org', name='name'),
                                                           cache_path='somewhere',
                                                           pants_path=None)])
    self.assertEqual(
      'Jar: org:name:::jar has no specified path.',
      str(cm.exception))

  def test_get_product_target_mappings_for_targets_respect_excludes(self):
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)
    self.add_excludes_for_targets(classpath_product, a)

    classpath_by_product = classpath_product.get_product_target_mappings_for_targets([a])

    self.assertEqual([], classpath_by_product)

  def test_get_product_target_mappings_for_targets_ignore_excludes(self):
    a = self.make_target('a', JvmTarget, excludes=[Exclude('com.example', 'lib')])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    resolved_jar = self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path,
                                                           conf='fred-conf')
    self.add_excludes_for_targets(classpath_product, a)

    classpath_target_tuples = classpath_product.get_product_target_mappings_for_targets([a], respect_excludes=False)

    expected_entry = ArtifactClasspathEntry(example_jar_path,
                                            resolved_jar.coordinate,
                                            resolved_jar.cache_path)
    self.assertEqual([(('fred-conf', expected_entry), a)], classpath_target_tuples)

  def test_get_product_target_mappings_for_targets_transitive(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    resolved_jar = self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)

    classpath_product.add_for_target(b, [('default', self.path('b/loose/classes/dir'))])
    classpath_product.add_for_target(a, [('default', self.path('a/loose/classes/dir')),
                                         ('default', self.path('an/internally/generated.jar'))])

    classpath_target_tuples = classpath_product.get_product_target_mappings_for_targets(a.closure(bfs=True))
    self.assertEqual([
      (('default', ArtifactClasspathEntry(example_jar_path,
                                          resolved_jar.coordinate,
                                          resolved_jar.cache_path)), a),
      (('default', ClasspathEntry(self.path('a/loose/classes/dir'))), a),
      (('default', ClasspathEntry(self.path('an/internally/generated.jar'))), a),
      (('default', ClasspathEntry(self.path('b/loose/classes/dir'))), b)],
      classpath_target_tuples)

  def test_get_product_target_mappings_for_targets_intransitive(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    resolved_jar = self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)

    classpath_product.add_for_target(b, [('default', self.path('b/loose/classes/dir'))])
    classpath_product.add_for_target(a, [('default', self.path('a/loose/classes/dir')),
                                         ('default', self.path('an/internally/generated.jar'))])

    classpath_target_tuples = classpath_product.get_product_target_mappings_for_targets([a])
    self.assertEqual([
      (('default', ArtifactClasspathEntry(example_jar_path,
                                          resolved_jar.coordinate,
                                          resolved_jar.cache_path)), a),
      (('default', ClasspathEntry(self.path('a/loose/classes/dir'))), a),
      (('default', ClasspathEntry(self.path('an/internally/generated.jar'))), a)],
      classpath_target_tuples)

  def test_get_classpath_entries_for_targets_dedup(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b])
    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()

    # resolved_jar is added for both a and b but should return only as one classpath entry
    resolved_jar = self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path,
                                                           conf='fred-conf')
    self.add_jar_classpath_element_for_path(classpath_product, b, example_jar_path,
                                            conf='fred-conf')
    classpath_target_tuples = classpath_product.get_classpath_entries_for_targets([a], respect_excludes=False)

    expected_entry = ArtifactClasspathEntry(example_jar_path,
                                            resolved_jar.coordinate,
                                            resolved_jar.cache_path)
    self.assertEqual([('fred-conf', expected_entry)], classpath_target_tuples)

  def test_get_artifact_classpath_entries_for_targets(self):
    b = self.make_target('b', JvmTarget, excludes=[Exclude('com.example', 'lib')])
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)
    example_jar_path = self._example_jar_path()
    resolved_jar = self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)

    # These non-artifact classpath entries should be ignored.
    classpath_product.add_for_target(b, [('default', self.path('b/loose/classes/dir'))])
    classpath_product.add_for_target(a, [('default', self.path('a/loose/classes/dir')),
                                         ('default', self.path('an/internally/generated.jar'))])

    classpath = classpath_product.get_artifact_classpath_entries_for_targets([a])
    self.assertEqual([('default', ArtifactClasspathEntry(example_jar_path,
                                                         resolved_jar.coordinate,
                                                         resolved_jar.cache_path))],
                     classpath)

  def test_get_internal_classpath_entries_for_targets(self):
    b = self.make_target('b', JvmTarget)
    a = self.make_target('a', JvmTarget, dependencies=[b])

    classpath_product = ClasspathProducts(self.pants_workdir)

    # This artifact classpath entry should be ignored.
    example_jar_path = self._example_jar_path()
    self.add_jar_classpath_element_for_path(classpath_product, a, example_jar_path)

    classpath_product.add_for_target(b, [('default', self.path('b/loose/classes/dir'))])
    classpath_product.add_for_target(a, [('default', self.path('a/loose/classes/dir')),
                                         ('default', self.path('an/internally/generated.jar'))])

    classpath = classpath_product.get_internal_classpath_entries_for_targets(a.closure(bfs=True))
    self.assertEqual([('default', ClasspathEntry(self.path('a/loose/classes/dir'))),
                      ('default', ClasspathEntry(self.path('an/internally/generated.jar'))),
                      ('default', ClasspathEntry(self.path('b/loose/classes/dir')))],
                     classpath)

  def test_create_canonical_classpath(self):
    a = self.make_target('a/b', JvmTarget)

    jar_path = 'ivy/jars/org.x/lib/x-1.0.jar'
    classpath_products = ClasspathProducts(self.pants_workdir)

    resolved_jar = ResolvedJar(M2Coordinate(org='org', name='x', rev='1.0'),
                               cache_path='somewhere',
                               pants_path=self._create_file(jar_path))

    classpath_products.add_for_target(a, [('default', self._create_file('a.jar')),
                                          ('default', self._create_file('resources'))])
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
                                            excludes={Exclude(org='org', name='y')})

    # incrementally delete the resource dendendency
    classpath_products = ClasspathProducts(self.pants_workdir)
    classpath_products.add_for_target(a, [('default', self._create_file('a.jar'))])
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
    classpath_products.add_for_target(a, [('default', self._create_file('a.jar')),
                                          ('default', self._create_file('b.jar'))])
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
                               pants_path=self._create_file(jar_path))
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
    canonical_classpath = ClasspathProducts.create_canonical_classpath(
      classpath_products, targets, libs_dir, save_classpath_file=True,
      internal_classpath_only=False, excludes=excludes)
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

  def _example_jar_path(self):
    return self.path('ivy/jars/com.example/lib/jars/123.4.jar')

  def path(self, p):
    return os.path.join(self.pants_workdir, p)

  def _create_file(self, p):
    return self.create_workdir_file(p)

  @staticmethod
  def add_jar_classpath_element_for_path(classpath_product,
                                         target,
                                         example_jar_path,
                                         conf=None):
    resolved_jar = resolved_example_jar_at(example_jar_path)
    classpath_product.add_jars_for_targets(targets=[target],
                                           conf=conf or 'default',
                                           resolved_jars=[resolved_jar])
    return resolved_jar

  @staticmethod
  def add_excludes_for_targets(classpath_product, *targets):
    classpath_product.add_excludes_for_targets(targets)

  def add_example_jar_classpath_element_for(self, classpath_product, target):
    self.add_jar_classpath_element_for_path(classpath_product, target, self._example_jar_path())
