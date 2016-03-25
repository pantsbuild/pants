# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_rmtree, touch
from pants_test.contrib.android.test_android_base import TestAndroidBase, distribution

from pants.contrib.android.tasks.dx_compile import DxCompile


class DxCompileTest(TestAndroidBase):

  UNPACKED_LIBS_LOC = os.path.join(get_buildroot(), '.pants.d/unpack-jars/unpack-libs/explode-jars')

  @classmethod
  def task_type(cls):
    return DxCompile

  @classmethod
  def base_unpacked_files(cls, package, app, version, location=None):
    location = location or cls.UNPACKED_LIBS_LOC
    unpacked_classes = {}
    class_files = ['Example.class', 'Hello.class', 'World.class']

    # This is the name of the directory that holds the unpacked libs - modeled after jar_target.id.
    unpacked_location = '{}-{}-{}.aar'.format(package, app, version)
    unpacked_classes[unpacked_location] = []
    for filename in class_files:
      new_file = os.path.join('a/b/c', filename)
      touch(os.path.join(location, unpacked_location, new_file))
      unpacked_classes[unpacked_location].append(new_file)
    return unpacked_classes

  @staticmethod
  def base_class_files(package, app):
    javac_classes = []
    for filename in ['Foo.class', 'Bar.class', 'Baz.class']:
      javac_classes.append('{}/{}/a/b/c/{}'.format(package, app, filename))
    return javac_classes

  def setUp(self):
    super(DxCompileTest, self).setUp()
    self.set_options(read_artifact_caches=None,
                     write_artifact_caches=None,
                     use_nailgun=False)

  def tearDown(self):
    # Delete any previously mocked files.
    safe_rmtree(os.path.join(self.UNPACKED_LIBS_LOC))

  def _mock_products(self, context, target, class_filenames=None, unpacked_filenames=None):
    # Create class files to mock the runtime_classpath product.
    self.add_to_runtime_classpath(context, target, {f: '' for f in (class_filenames or [])})

    # Create class files to mock the unpack_libraries product.
    for archive in (unpacked_filenames or []):
      relative_unpack_dir = (os.path.join(self.UNPACKED_LIBS_LOC, archive))

      unpacked_products = context.products.get('unpacked_libraries')
      unpacked_products.add(target, self.build_root).append(relative_unpack_dir)

  def _gather(self, context, target):
    """Creates a task for the context, and yields the files that would be placed in the dex."""
    gathered = []
    for entry in self.create_task(context)._gather_dex_entries(target):
      if ClasspathUtil.is_jar(entry) or ClasspathUtil.is_dir(entry):
        gathered.extend(ClasspathUtil.classpath_entries_contents([entry]))
      else:
        gathered.append(entry)
    return gathered

  def test_gather_dex_entries(self):
    with self.android_binary() as binary:
      # Add class files to runtime_classpath product.
      context = self.context(target_roots=binary)
      classes = self.base_class_files('org.pantsbuild.android', 'example')
      self._mock_products(context, binary, classes)

      # Test that the proper entries are gathered for inclusion in the dex file.
      class_files = self._gather(context, binary)
      for filename in classes:
        self.assertIn(filename, class_files)

  def test_gather_dex_entries_from_deps(self):
    # Make sure runtime_classpath are being gathered from a binary's android_library dependencies.
    with self.android_library() as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        classes = self.base_class_files('org.pantsbuild.android', 'example')
        self._mock_products(context, android_library, classes)

        gathered_classes = self._gather(context, binary)
        for class_file in classes:
          self.assertIn(class_file, gathered_classes)

  def test_gather_unpacked_libs(self):
    # Ensure that classes from unpacked android_dependencies are included in classes bound for dex.
    with self.android_library() as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        classes = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, android_library, [], classes)

        gathered_classes = self._gather(context, binary)
        for location in classes:
          for class_file in classes[location]:
            file_path = os.path.join(self.UNPACKED_LIBS_LOC, location, class_file)
            self.assertIn(file_path, gathered_classes)

  def test_gather_both_compiled_and_unpacked_classes(self):
    with self.android_library() as library:
      with self.android_binary(dependencies=[library]) as binary:
        context = self.context(target_roots=binary)
        classes = self.base_class_files('org.pantsbuild.android', 'example')
        unpacked_classes = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, library, classes, unpacked_classes)

        gathered_classes = self._gather(context, binary)

        # Test that compiled classes are gathered for dex file.
        for class_file in classes:
          self.assertIn(class_file, gathered_classes)

        # Test that unpacked classes are gathered for dex file.
        for location in unpacked_classes:
          for class_file in unpacked_classes[location]:
            file_path = os.path.join(self.UNPACKED_LIBS_LOC, location, class_file)
            self.assertIn(file_path, gathered_classes)

  # UnpackedLibraries are filtered by DxCompile to allow binaries to share unpacked libraries.
  # The following tests check the filter functionality.
  def test_include_filter_in_gather_dex_entries(self):
    with self.android_library(include_patterns=['**/a/**/Example.class']) as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        classes = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, android_library, [], classes)

        gathered_classes = self._gather(context, binary)
        for location in classes:
          included_file = os.path.join(self.UNPACKED_LIBS_LOC, location, 'a/b/c/Example.class')
          excluded_file = os.path.join(self.UNPACKED_LIBS_LOC, location, 'a/b/c/Hello.class')
          self.assertIn(included_file, gathered_classes)
          self.assertNotIn(excluded_file, gathered_classes)

  def test_exclude_filter_in_gather_dex_entries(self):
    with self.android_library(exclude_patterns=['**/a/**/Example.class']) as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        classes = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, android_library, [], classes)

        gathered_classes = self._gather(context, binary)
        for location in classes:
          included_file = os.path.join(self.UNPACKED_LIBS_LOC, location, 'a/b/c/Hello.class')
          excluded_file = os.path.join(self.UNPACKED_LIBS_LOC, location, 'a/b/c/Example.class')
          self.assertIn(included_file, gathered_classes)
          self.assertNotIn(excluded_file, gathered_classes)

  def test_both_filters_in_gather_dex_entries(self):
    with self.android_library(include_patterns=['**/a/**/Hello.class'],
                              exclude_patterns=['**/a/**/Example.class']) as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        classes = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, android_library, [], classes)

        gathered_classes = self._gather(context, binary)
        for location in classes:
          included_file = os.path.join(self.UNPACKED_LIBS_LOC, location, 'a/b/c/Hello.class')
          excluded_file = os.path.join(self.UNPACKED_LIBS_LOC, location, 'a/b/c/Example.class')
          self.assertIn(included_file, gathered_classes)
          self.assertNotIn(excluded_file, gathered_classes)

  def test_no_matching_classes(self):
    # No classpath entries and no classes that pass the file filter.
    with self.android_library(include_patterns=['**/a/**/*.NONE']) as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        with self.android_library(target_name='other') as other:
          context = self.context(target_roots=binary)
          # Initialize the classpath, but not for the relevant target.
          self._mock_products(context, other, [])
          # Then run for the empty target.
          dx_task = self.create_task(context)

          with self.assertRaises(DxCompile.EmptyDexError):
            dx_task.execute()

  # Test deduping and version conflicts within android_dependencies. The Dx tool returns failure if
  # more than one copy of a class is packed into the dex file and it is very easy to fetch
  # duplicate libraries (as well as conflicting versions) from the Android SDK. As long as the
  # version number is the same, pants silently dedupes. Version conflicts raise an exception.
  def test_filter_unpacked_dir(self):
    with self.android_library() as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        unpacked_classes = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, android_library, [], unpacked_classes)
        dx_task = self.create_task(context)

        gathered_classes = dx_task._filter_unpacked_dir(android_library, self.UNPACKED_LIBS_LOC, {})
        for location in unpacked_classes:
          for class_file in unpacked_classes[location]:
            file_path = os.path.join(self.UNPACKED_LIBS_LOC, location, class_file)
            self.assertIn(file_path, gathered_classes)

  def test_duplicate_library_version_deps(self):
    with self.android_library() as library:
      with self.android_binary(dependencies=[library]) as binary:
        context = self.context(target_roots=binary)
        first_unpacked = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        duplicate_unpacked = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        self._mock_products(context, library, [], first_unpacked)
        self._mock_products(context, library, [], duplicate_unpacked)

        gathered_classes = self._gather(context, binary)
        # Should be just one copy of each unpackaged class gathered.
        self.assertEqual(len([c for c in gathered_classes if c.endswith('.class')]), 3)

  def test_dependency_version_conflict(self):
    with self.android_library() as android_library:
      with self.android_binary(dependencies=[android_library]) as binary:
        context = self.context(target_roots=binary)
        first_unpacked = self.base_unpacked_files('org.pantsbuild.android', 'example', '1.0')
        conflicting = self.base_unpacked_files('org.pantsbuild.android', 'example', '2.0')
        self._mock_products(context, android_library, [], first_unpacked)
        self._mock_products(context, android_library, [], conflicting)

        # Raises an exception when gathering classes with conflicting version numbers.
        with self.assertRaises(DxCompile.DuplicateClassFileException):
          list(self._gather(context, binary))

  # Test misc. methods
  def test_render_args(self):
    tempdir = '/temp/out'
    dx_task = self.create_task(self.context())
    classes = ['example/a/b/c/Example.class']
    args = dx_task._render_args(tempdir, classes)
    expected_args = ['--dex', '--no-strict', '--output=/temp/out/{}'.format(dx_task.DEX_NAME)]
    expected_args.extend(classes)
    self.assertEqual(args, expected_args)

  def test_product_types(self):
    self.assertEqual(['dex'], DxCompile.product_types())

  def test_dx_jar_tool(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist)
        task = self.create_task(self.context())
        dx_jar = os.path.join(dist, 'build-tools', android_binary.build_tools_version, 'lib/dx.jar')
        self.assertEqual(task.dx_jar_tool(android_binary.build_tools_version), dx_jar)

  def test_force_build_tools_version_dx_jar_tool(self):
    with distribution() as dist:
      with self.android_binary() as android_binary:
        self.set_options(sdk_path=dist, build_tools_version='20.0.0')
        task = self.create_task(self.context())
        dx_jar = os.path.join(dist, 'build-tools', '20.0.0', 'lib/dx.jar')
        self.assertEqual(task.dx_jar_tool(android_binary.build_tools_version), dx_jar)

  def test_is_dex_target(self):
    with self.android_library() as library:
      with self.android_binary() as binary:
        self.assertTrue(DxCompile.is_android_binary(binary))
        self.assertFalse(DxCompile.is_android_binary(library))
