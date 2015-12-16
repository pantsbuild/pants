# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.base.exceptions import TaskError
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_mkdir, safe_mkdir_for, touch
from pants_test.jvm.jvm_task_test_base import JvmTaskTestBase


class DuplicateDetectorTest(JvmTaskTestBase):

  @classmethod
  def task_type(cls):
    return DuplicateDetector

  def setUp(self):
    super(DuplicateDetectorTest, self).setUp()

    self.classes_dir = os.path.join(self.test_workdir, 'classes')
    safe_mkdir(self.classes_dir)

    def generate_class(name):
      path = os.path.join(self.classes_dir, name)
      touch(path)
      return path

    test_class_path = generate_class('com/twitter/Test.class')
    duplicate_class_path = generate_class('com/twitter/commons/Duplicate.class')
    unique_class_path = generate_class('org/apache/Unique.class')
    unicode_class_path = generate_class('cucumber/api/java/zh_cn/假如.class')

    def generate_jar(path, *class_name):
      jar_path = os.path.join(self.test_workdir, 'jars', path)
      safe_mkdir_for(jar_path)
      with open_zip(jar_path, 'w') as zipfile:
        for clazz in class_name:
          zipfile.write(clazz, os.path.relpath(clazz, self.classes_dir))
        return jar_path

    self.test_jar = generate_jar('test.jar', test_class_path, duplicate_class_path)
    self.dups_jar = generate_jar('dups.jar', duplicate_class_path, unique_class_path)
    self.no_dups_jar = generate_jar('no_dups.jar', unique_class_path)
    self.unicode_jar = generate_jar('unicode_class.jar', unicode_class_path)

    def resolved_jarlib(name, jar_path):
      resolved_jar = ResolvedJar(M2Coordinate(org='org.example', name=name, rev='0.0.1'),
                                 cache_path=jar_path,
                                 pants_path=jar_path)
      jar_dep = JarDependency(org='org.example', name=name, rev='0.0.1')
      jar_library = self.make_target(spec='3rdparty:{}'.format(name),
                                     target_type=JarLibrary,
                                     jars=[jar_dep])
      return jar_library, resolved_jar

    self.test_jarlib, self.test_resolved_jar = resolved_jarlib('test', self.test_jar)
    self.dups_jarlib, self.dups_resolved_jar = resolved_jarlib('dups', self.dups_jar)
    self.no_dups_jarlib, self.no_dups_resolved_jar = resolved_jarlib('no_dups', self.no_dups_jar)
    self.unicode_jarlib, self.unicode_resolved_jar = resolved_jarlib('unicode', self.unicode_jar)

  def _setup_external_duplicate(self):
    jvm_binary = self.make_target(spec='src/java/com/twitter:thing',
                                  target_type=JvmBinary,
                                  dependencies=[self.test_jarlib, self.dups_jarlib])
    context = self.context(target_roots=[jvm_binary])
    task = self.create_task(context)

    classpath = self.get_runtime_classpath(context)
    classpath.add_jars_for_targets([self.test_jarlib], 'default', [self.test_resolved_jar])
    classpath.add_jars_for_targets([self.dups_jarlib], 'default', [self.dups_resolved_jar])
    return task, jvm_binary

  def test_duplicate_found_external(self):
    self.set_options(fail_fast=False)
    task, jvm_binary = self._setup_external_duplicate()
    conflicts_by_binary = task.execute()
    expected = {
      jvm_binary: {
        ('org.example-dups-0.0.1.jar', 'org.example-test-0.0.1.jar'):
          {'com/twitter/commons/Duplicate.class'}
      }
    }
    self.assertEqual(expected, conflicts_by_binary)

  def test_duplicate_skip(self):
    self.set_options(fail_fast=False, skip=True)
    task, _ = self._setup_external_duplicate()
    conflicts_by_binary = task.execute()
    self.assertEqual(None, conflicts_by_binary)

  def test_duplicate_excluded_file(self):
    self.set_options(fail_fast=False, excludes=[], exclude_files=['Duplicate.class'])
    task, jvm_binary = self._setup_external_duplicate()
    conflicts_by_binary = task.execute()
    self.assertEqual({}, conflicts_by_binary)

  def _setup_internal_duplicate(self):
    java_library = self.make_target(spec='src/java/com/twitter:lib',
                                    target_type=JavaLibrary)
    jvm_binary = self.make_target(spec='src/java/com/twitter:thing',
                                  target_type=JvmBinary,
                                  dependencies=[java_library])
    context = self.context(target_roots=[jvm_binary])
    task = self.create_task(context)

    classpath = self.get_runtime_classpath(context)
    classpath.add_for_target(java_library, [('default', self.classes_dir)])
    classpath.add_for_target(jvm_binary, [('default', self.classes_dir)])
    return task, jvm_binary

  def test_duplicate_found_internal(self):
    self.set_options(fail_fast=False)
    task, jvm_binary = self._setup_internal_duplicate()
    conflicts_by_binary = task.execute()

    expected = {
      jvm_binary: {
        ('src/java/com/twitter:lib', 'src/java/com/twitter:thing'):
          {'com/twitter/Test.class',
           'com/twitter/commons/Duplicate.class',
           'org/apache/Unique.class',
           'cucumber/api/java/zh_cn/假如.class'}
      }
    }
    self.assertEqual(expected, conflicts_by_binary)

  def test_duplicate_excluded_internal(self):
    self.set_options(fail_fast=False, excludes=[], exclude_files=['Duplicate.class', '假如.class'])
    task, jvm_binary = self._setup_internal_duplicate()
    conflicts_by_binary = task.execute()

    expected = {
      jvm_binary: {
        ('src/java/com/twitter:lib', 'src/java/com/twitter:thing'):
          {'com/twitter/Test.class',
           'org/apache/Unique.class'}
      }
    }
    self.assertEqual(expected, conflicts_by_binary)

  def test_duplicate_found_mixed(self):
    self.set_options(fail_fast=False)

    jvm_binary = self.make_target(spec='src/java/com/twitter:thing',
                                  target_type=JvmBinary,
                                  dependencies=[self.test_jarlib])
    context = self.context(target_roots=[jvm_binary])
    task = self.create_task(context)

    classpath = self.get_runtime_classpath(context)
    classpath.add_for_target(jvm_binary, [('default', self.classes_dir)])
    classpath.add_jars_for_targets([self.test_jarlib], 'default', [self.test_resolved_jar])

    conflicts_by_binary = task.execute()

    expected = {
      jvm_binary: {
        ('org.example-test-0.0.1.jar', 'src/java/com/twitter:thing'):
          {'com/twitter/Test.class', 'com/twitter/commons/Duplicate.class'}
      }
    }
    self.assertEqual(expected, conflicts_by_binary)

  def test_duplicate_not_found(self):
    self.set_options(fail_fast=True)

    jvm_binary = self.make_target(spec='src/java/com/twitter:thing',
                                  target_type=JvmBinary,
                                  dependencies=[self.no_dups_jarlib,
                                                self.unicode_jarlib])
    context = self.context(target_roots=[jvm_binary])
    task = self.create_task(context)

    classpath = self.get_runtime_classpath(context)
    classpath.add_jars_for_targets([self.no_dups_jarlib], 'default', [self.no_dups_resolved_jar])
    classpath.add_jars_for_targets([self.unicode_jarlib], 'default', [self.unicode_resolved_jar])

    conflicts_by_binary = task.execute()
    self.assertEqual({}, conflicts_by_binary)

  def test_fail_fast_error_raised(self):
    self.set_options(fail_fast=True)

    jvm_binary = self.make_target(spec='src/java/com/twitter:thing',
                                  target_type=JvmBinary,
                                  dependencies=[self.test_jarlib])
    context = self.context(target_roots=[jvm_binary])
    task = self.create_task(context)

    classpath = self.get_runtime_classpath(context)
    classpath.add_for_target(jvm_binary, [('default', self.classes_dir)])
    classpath.add_jars_for_targets([self.test_jarlib], 'default', [self.test_resolved_jar])

    with self.assertRaises(TaskError):
      task.execute()

  def test_is_excluded_default(self):
    task = self.create_task(self.context())
    self.assertFalse(task._is_excluded('foo'))
    self.assertFalse(task._is_excluded('foo/BCKEY.DSA'))
    # excluded_files: No directroy
    self.assertTrue(task._is_excluded('.DS_Store'))
    # excluded_files: Mixed case
    self.assertTrue(task._is_excluded('NOTICE.txt'))
    # excluded_files: Leading directory
    self.assertTrue(task._is_excluded('/foo/bar/dependencies'))
    # excluded_dirs:
    self.assertTrue(task._is_excluded('META-INF/services/foo'))
    # excluded_patterns:
    self.assertTrue(task._is_excluded('META-INF/BCKEY.RSA'))

  def test_is_excluded_pattern(self):
    self.set_options(exclude_patterns=[r'.*/garbage\.'])
    task = self.create_task(self.context())
    self.assertTrue(task._is_excluded('foo/garbage.txt'))

  def test_is_excluded_files(self):
    self.set_options(excludes=None, exclude_files=['bckey.dsa'])
    task = self.create_task(self.context())
    self.assertTrue(task._is_excluded('foo/BCKEY.DSA'))

    # Defaults are now overridden
    self.assertFalse(task._is_excluded('NOTICE.txt'))

  def test_is_excluded_files(self):
    self.set_options(exclude_dirs=['org/duplicated'])
    task = self.create_task(self.context())
    self.assertTrue(task._is_excluded('org/duplicated/FOO'))

    # Defaults are now overridden
    self.assertFalse(task._is_excluded('META-INF/services/foo'))
