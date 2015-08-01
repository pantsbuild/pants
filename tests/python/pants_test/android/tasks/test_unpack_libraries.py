# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from textwrap import dedent

from pants.backend.android.targets.android_dependency import AndroidDependency
from pants.backend.android.targets.android_library import AndroidLibrary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.unpack_libraries import UnpackLibraries
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.base.build_file_aliases import BuildFileAliases
from pants.fs.archive import ZIP
from pants.util.contextutil import open_zip, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir, safe_open, safe_walk, touch
from pants_test.android.test_android_base import TestAndroidBase


class UnpackLibrariesTest(TestAndroidBase):
  """Test the .aar and .jar unpacking methods in pants.backend.android.tasks.unpack_libraries."""

  @classmethod
  def task_type(cls):
    return UnpackLibraries

  @classmethod
  def _add_ivy_imports_product(cls, foo_target, android_dep, unpack_task):
    ivy_imports_product = unpack_task.context.products.get('ivy_imports')
    ivy_imports_product.add(foo_target, os.path.dirname(android_dep),
                            [os.path.basename(android_dep)])

  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'android_dependency': AndroidDependency,
        'android_library': AndroidLibrary,
        'jar_library': JarLibrary,
        'target': Dependencies
      },
      objects={
        'jar': JarDependency,
      },
    )

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
    archive = 'org.pantsbuild.example-1.0'
    outdir = task.unpacked_aar_location(archive)
    self.assertEqual(os.path.join(task.workdir, archive), outdir)

  def test_jar_out(self):
    task = self.create_task(self.context())
    archive = 'org.pantsbuild.example-1.0'
    outdir = task.unpacked_jar_location(archive)
    self.assertEqual(os.path.join(task.workdir, 'explode-jars', archive), outdir)

  def test_create_classes_jar_target(self):
    with self.android_library() as android_library:
      with temporary_file() as jar:
        task = self.create_task(self.context())
        archive = 'org.pantsbuild.example-1.0'
        created_target = task.create_classes_jar_target(android_library, archive, jar)
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
          archive = 'org.pantsbuild.example-1.0'
          created_target = task.create_resource_target(library, archive, manifest.name, res)

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
        archive = 'org.pantsbuild.example-1.0'
        created_library = task.create_android_library_target(android_library, archive, contents)

        self.assertEqual(created_library.derived_from, android_library)
        self.assertTrue(created_library.is_synthetic)
        self.assertTrue(isinstance(created_library, AndroidLibrary))
        self.assertEqual(android_library.include_patterns, created_library.include_patterns)
        self.assertEqual(android_library.exclude_patterns, created_library.exclude_patterns)
        self.assertEqual(len(created_library.dependencies), 2)
        for dep in created_library.dependencies:
          self.assertTrue(isinstance(dep, AndroidResources) or isinstance(dep, JarLibrary))

  def test_no_classes_jar(self):
    with self.android_library(include_patterns=['**/*.class']) as android_library:
      with temporary_dir() as temp:
        contents = self.unpacked_aar_library(temp, classes_jar=False)
        task = self.create_task(self.context())
        archive = 'org.pantsbuild.example-1.0'
        created_library = task.create_android_library_target(android_library, archive, contents)
        self.assertEqual(len(created_library.dependencies), 1)
        for dep in created_library.dependencies:
          isinstance(dep, AndroidResources)

  def test_no_resources(self):
    with self.android_library() as android_library:
      with temporary_dir() as temp:
        contents = self.unpacked_aar_library(temp, classes_jar=False)
        task = self.create_task(self.context())
        archive = 'org.pantsbuild.example-1.0'
        created_library = task.create_android_library_target(android_library, archive, contents)
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

  def create_unpack_build_file(self):
    self.add_to_build_file('unpack', dedent('''
            android_library(name='test',
              libraries=['unpack/libs:test-jar'],
              include_patterns=[
                'a/b/c/*.class',
              ],
             )
            '''))

  def test_unpack_jar_library(self):
    # Test for when the imported library is a jarfile.
    with temporary_dir() as temp:
      jar_file = self.create_jarfile(temp, 'org.pantsbuild.android.test',
                                     filenames=['a/b/c/Any.class', 'a/b/d/Thing.class'])
      self.create_unpack_build_file()
      target_name = 'unpack:test'
      self._make_android_dependency('test-jar', jar_file, '1.0')
      test_target = self.target(target_name)
      files = self.unpack_libraries(target_name, jar_file)

      # If the android_library imports a jar, files are unpacked but no new targets are created.
      self.assertIn('Thing.class', files)
      self.assertEqual(len(test_target.dependencies), 0)

  def test_unexpected_archive_type(self):
    with temporary_dir() as temp:
      aar = self.create_aarfile(temp, 'org.pantsbuild.android.test')
      unexpected_archive = os.path.join(temp, 'org.pantsbuild.android.test{}'.format('.other'))
      os.rename(aar, unexpected_archive)
      self.create_unpack_build_file()

      target_name = 'unpack:test'
      self._make_android_dependency('test-jar', unexpected_archive, '1.0')

      with self.assertRaises(UnpackLibraries.UnexpectedArchiveType):
        self.unpack_libraries(target_name, unexpected_archive)

  # Test aar unpacking and invalidation

  def test_ivy_args(self):
    # A regression test for ivy_mixin_task. UnpackLibraries depends on the mapped jar filename
    # being unique and including the version number. If you are making a change to
    # ivy_task_mixin._get_ivy_args() that maintains both then feel free to update this test.
    ivy_args = [
      '-retrieve', '{}/[organisation]/[artifact]/[conf]/'
                   '[organisation]-[artifact]-[revision](-[classifier]).[ext]'.format('foo'),
      '-symlink',
      ]
    self.assertEqual(ivy_args, IvyTaskMixin._get_ivy_args('foo'))

  # There is a bit of fudging here. In practice, the jar name is transformed by ivy into
  # '[organisation]-[artifact]-[revision](-[classifier]).[ext]'. The unpack_libraries task does not
  # care about the details of the imported jar name but it does rely on that name being unique and
  # including the version number.
  def _approximate_ivy_mapjar_name(self, archive, android_archive):
    # This basically creates a copy named after the target.id + file extension.
    location = os.path.dirname(archive)
    ivy_mapjar_name = os.path.join(location,
                                   '{}{}'.format(android_archive, os.path.splitext(archive)[1]))
    shutil.copy(archive, ivy_mapjar_name)
    return ivy_mapjar_name

  def _make_android_dependency(self, name, library_file, version):
    build_file = os.path.join(self.build_root, 'unpack', 'libs', 'BUILD')
    if os.path.exists(build_file):
      os.remove(build_file)
    self.add_to_build_file('unpack/libs', dedent('''
      android_dependency(name='{name}',
        jars=[
          jar(org='com.example', name='bar', rev='{version}', url='file:///{filepath}'),
        ],
      )
    '''.format(name=name, version=version, filepath=library_file)))

  def unpack_libraries(self, target_name, aar_file):
    test_target = self.target(target_name)
    task = self.create_task(self.context(target_roots=[test_target]))

    for android_archive in test_target.imported_jars:
      target_jar = self._approximate_ivy_mapjar_name(aar_file, android_archive)
      self._add_ivy_imports_product(test_target, target_jar, task)
    task.execute()

    # Gather classes found when unpacking the aar_file.
    aar_name = os.path.basename(target_jar)
    files = []
    jar_location = task.unpacked_jar_location(aar_name)
    for _, _, filename in safe_walk(jar_location):
      files.extend(filename)
    return files

  def test_unpack_aar_files_and_invalidation(self):
    with temporary_dir() as temp:
      aar = self.create_aarfile(temp, 'org.pantsbuild.android.test')
      self.create_unpack_build_file()

      target_name = 'unpack:test'
      self._make_android_dependency('test-jar', aar, '1.0')
      files = self.unpack_libraries(target_name, aar)
      self.assertIn('Foo.class', files)

      # Reset build graph to dismiss all the created targets.
      self.reset_build_graph()

      # Create a new copy of the archive- adding a sentinel file but without bumping the version.
      new_aar = self.create_aarfile(temp, 'org.pantsbuild.android.test',
                                    filenames=['a/b/c/Baz.class'])

      # Call task a 2nd time but the sentinel file is not found because we didn't bump version.
      files = self.unpack_libraries(target_name, new_aar)
      self.assertNotIn('Baz.class', files)

      # Now bump version and this time the aar is unpacked and the sentinel file is found.
      self.reset_build_graph()
      self._make_android_dependency('test-jar', new_aar, '2.0')
      files = self.unpack_libraries(target_name, new_aar)
      self.assertIn('Baz.class', files)
