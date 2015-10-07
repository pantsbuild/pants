# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.targets.android_dependency import AndroidDependency
from pants.backend.android.targets.android_library import AndroidLibrary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.unpack_libraries import UnpackLibraries
from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.fs.archive import ZIP
from pants.util.contextutil import open_zip, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir, safe_open, safe_walk, touch
from pants_test.android.test_android_base import TestAndroidBase


class UnpackLibrariesTest(TestAndroidBase):
  """Test the .aar and .jar unpacking methods in pants.backend.android.tasks.unpack_libraries."""

  @classmethod
  def task_type(cls):
    return UnpackLibraries

  def unpacked_aar_library(self, location, manifest=True, classes_jar=True, resources=True,
                           filenames=None):
    """Mock the contents of an aar file, with optional components and additional files."""
    if manifest:
      manifest_file = os.path.join(location, 'AndroidManifest.xml')
      touch(manifest_file)
      with safe_open(manifest_file, 'w') as fp:
        fp.write(self.android_manifest())
        fp.close()
    if classes_jar:
      self.create_jarfile(location, filenames=filenames)
    if resources:
      safe_mkdir(os.path.join(location, 'res'))
    return location

  def create_aarfile(self, location, name, filenames=None):
    """Create an aar file, using the contents created by self.unpacked_aar_library."""
    with temporary_dir() as temp:
      aar_contents = self.unpacked_aar_library(temp, filenames=filenames)
      archive = ZIP.create(aar_contents, location, name)
      aar = os.path.join(location, '{}.aar'.format(name))
      os.rename(archive, aar)
      return aar

  def create_jarfile(self, location, name=None, filenames=None):
    """Create a sample jar file."""
    name = '{}.jar'.format(name or 'classes')
    jar_name = os.path.join(location, name)
    with open_zip(jar_name, 'w') as library:
      library.writestr('a/b/c/Foo.class', '0xCAFEBABE')
      library.writestr('a/b/c/Bar.class', '0xCAFEBABE')
      if filenames:
        for class_file in filenames:
          library.writestr(class_file, '0xCAFEBABE')
    return jar_name

  def test_unpack_smoke(self):
    task = self.create_task(self.context())
    task.execute()

  def test_is_library(self):
    with self.android_library() as android_library:
      task = self.create_task(self.context())
      self.assertTrue(task.is_library(android_library))

  def test_detect_nonlibrary(self):
    with self.android_target() as android_target:
      task = self.create_task(self.context())
      self.assertFalse(task.is_library(android_target))

  def test_aar_out(self):
    task = self.create_task(self.context())
    coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0', ext='aar')
    outdir = task.unpacked_aar_location(coordinate)
    self.assertEqual(os.path.join(task.workdir, 'org.pantsbuild-example-1.0.aar'), outdir)

  def test_jar_out(self):
    task = self.create_task(self.context())
    coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0', ext='jar')
    outdir = task.unpacked_jar_location(coordinate)
    self.assertEqual(os.path.join(task.workdir, 'explode-jars', 'org.pantsbuild-example-1.0.jar'),
                     outdir)

  def test_create_classes_jar_target(self):
    with self.android_library() as android_library:
      with temporary_file() as jar:
        task = self.create_task(self.context())
        coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0')
        created_target = task.create_classes_jar_target(android_library, coordinate, jar)
        self.assertEqual(created_target.derived_from, android_library)
        self.assertTrue(created_target.is_synthetic)
        self.assertTrue(isinstance(created_target, JarLibrary))

  def test_create_resource_target(self):
    with self.android_library() as library:
      with temporary_file() as manifest:
        with temporary_dir() as res:
          manifest.write(self.android_manifest())
          manifest.close()
          task = self.create_task(self.context())
          coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0')
          created_target = task.create_resource_target(library, coordinate, manifest.name, res)

          self.assertEqual(created_target.derived_from, library)
          self.assertTrue(created_target.is_synthetic)
          self.assertTrue(isinstance(created_target, AndroidResources))
          self.assertEqual(created_target.resource_dir, res)
          self.assertEqual(created_target.manifest.path, manifest.name)

  def test_create_android_library_target(self):
    with self.android_library(include_patterns=['**/*.class']) as android_library:
      with temporary_dir() as temp:
        contents = self.unpacked_aar_library(temp)
        task = self.create_task(self.context())
        coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0')
        created_library = task.create_android_library_target(android_library, coordinate, contents)

        self.assertEqual(created_library.derived_from, android_library)
        self.assertTrue(created_library.is_synthetic)
        self.assertTrue(isinstance(created_library, AndroidLibrary))
        self.assertEqual(android_library.payload.include_patterns, created_library.payload.include_patterns)
        self.assertEqual(android_library.payload.exclude_patterns, created_library.payload.exclude_patterns)
        self.assertEqual(len(created_library.dependencies), 2)
        for dep in created_library.dependencies:
          self.assertTrue(isinstance(dep, AndroidResources) or isinstance(dep, JarLibrary))

  def test_no_classes_jar(self):
    with self.android_library(include_patterns=['**/*.class']) as android_library:
      with temporary_dir() as temp:
        contents = self.unpacked_aar_library(temp, classes_jar=False)
        task = self.create_task(self.context())
        coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0')
        created_library = task.create_android_library_target(android_library, coordinate, contents)
        self.assertEqual(len(created_library.dependencies), 1)
        for dep in created_library.dependencies:
          isinstance(dep, AndroidResources)

  def test_no_resources(self):
    with self.android_library() as android_library:
      with temporary_dir() as temp:
        contents = self.unpacked_aar_library(temp, classes_jar=False)
        task = self.create_task(self.context())
        coordinate = M2Coordinate(org='org.pantsbuild', name='example', rev='1.0')
        created_library = task.create_android_library_target(android_library, coordinate, contents)
        self.assertEqual(len(created_library.dependencies), 1)
        for dep in created_library.dependencies:
          isinstance(dep, JarLibrary)

  def test_no_manifest(self):
    with self.android_library(include_patterns=['**/*.class']) as android_library:
      with temporary_dir() as temp:
        contents = self.unpacked_aar_library(temp, manifest=False)
        task = self.create_task(self.context())
        archive = 'org.pantsbuild.example-1.0'

        with self.assertRaises(UnpackLibraries.MissingElementException):
          task.create_android_library_target(android_library, archive, contents)

  # Test unpacking process.
  def create_android_library(self, rev, library_file):
    _, ext = os.path.splitext(library_file)
    coord = M2Coordinate(org='com.example', name='bar', rev=rev, ext=ext[1:])
    dep_spec = 'unpack/libs:{}-{}-{}'.format(coord.org, coord.name, coord.rev)
    adroid_dep = self.make_target(spec=dep_spec,
                                  target_type=AndroidDependency,
                                  jars=[JarDependency(org=coord.org, name=coord.name, rev=coord.rev,
                                                      url='file:{}'.format(library_file))])
    target = self.make_target(spec='unpack:test', target_type=AndroidLibrary,
                              libraries=[adroid_dep.address.spec],
                              include_patterns=['a/b/c/*.class'])
    return target, coord

  def test_unpack_jar_library(self):
    # Test for when the imported library is a jarfile.
    with temporary_dir() as temp:
      jar_file = self.create_jarfile(temp, 'org.pantsbuild.android.test',
                                     filenames=['a/b/c/Any.class', 'a/b/d/Thing.class'])

      test_target, coordinate = self.create_android_library(rev='1.0', library_file=jar_file)
      original_dependencies = list(test_target.dependencies)
      files = self.unpack_libraries(target=test_target, aar_file=jar_file, coordinate=coordinate)

      # If the android_library imports a jar, files are unpacked but no new targets are created.
      self.assertEqual(sorted(['Any.class', 'Thing.class', 'Foo.class', 'Bar.class']),
                       sorted(files))
      self.assertEqual(original_dependencies, test_target.dependencies)

  def test_unexpected_archive_type(self):
    with temporary_dir() as temp:
      aar = self.create_aarfile(temp, 'org.pantsbuild.android.test')
      unexpected_archive = os.path.join(temp, 'org.pantsbuild.android.test{}'.format('.other'))
      os.rename(aar, unexpected_archive)

      lib, coordinate = self.create_android_library(rev='1.0', library_file=unexpected_archive)

      with self.assertRaises(UnpackLibraries.UnexpectedArchiveType):
        self.unpack_libraries(target=lib, aar_file=unexpected_archive, coordinate=coordinate)

  def unpack_libraries(self, target, aar_file, coordinate):
    context = self.context(target_roots=[target])
    task = self.create_task(context)

    jar_import_products = context.products.get_data(JarImportProducts, init_func=JarImportProducts)
    jar_import_products.imported(target, coordinate, aar_file)

    task.execute()

    # Gather classes found when unpacking the aar_file.
    files = []
    jar_location = task.unpacked_jar_location(coordinate)
    for _, _, filenames in safe_walk(jar_location):
      files.extend(filenames)
    return files

  def test_unpack_aar_files_and_invalidation(self):
    with temporary_dir() as temp:
      aar = self.create_aarfile(temp, 'org.pantsbuild.android.test')

      lib, coordinate = self.create_android_library(rev='1.0', library_file=aar)

      files = self.unpack_libraries(target=lib, aar_file=aar, coordinate=coordinate)
      self.assertIn('Foo.class', files)

      # Reset build graph to dismiss all the created targets.
      self.reset_build_graph()

      # Create a new copy of the archive- adding a sentinel file but without bumping the version.
      new_aar = self.create_aarfile(temp, 'org.pantsbuild.android.test',
                                    filenames=['a/b/c/Baz.class'])
      lib, coordinate = self.create_android_library(rev='1.0', library_file=new_aar)

      # Call task a 2nd time but the sentinel file is not found because we didn't bump version.
      files = self.unpack_libraries(target=lib, aar_file=new_aar, coordinate=coordinate)
      self.assertNotIn('Baz.class', files)

      # Now bump version and this time the aar is unpacked and the sentinel file is found.
      self.reset_build_graph()
      lib, coordinate = self.create_android_library(rev='2.0', library_file=aar)
      files = self.unpack_libraries(target=lib, aar_file=new_aar, coordinate=coordinate)
      self.assertIn('Baz.class', files)
