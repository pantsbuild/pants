# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os

from twitter.common.contextutil import open_zip, temporary_dir, temporary_file

from pants.backend.jvm.tasks.jar_task import JarTask
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree
from pants_test.jvm.jar_task_test_base import JarTaskTestBase


class JarTaskTest(JarTaskTestBase):

  class TestJarTask(JarTask):
    def execute(self):
      pass

  def setUp(self):
    super(JarTaskTest, self).setUp()

    self.workdir = safe_mkdtemp()
    self.jar_task = self.prepare_execute(self.context(), self.workdir, self.TestJarTask)

  def tearDown(self):
    super(JarTaskTest, self).tearDown()

    if self.workdir:
      safe_rmtree(self.workdir)

  @contextmanager
  def jarfile(self):
    with temporary_file() as fd:
      fd.close()
      yield fd.name

  def assert_listing(self, jar, *expected_items):
    self.assertEquals(set(['META-INF/', 'META-INF/MANIFEST.MF']) | set(expected_items),
                      set(jar.namelist()))

  def test_update_write(self):
    with temporary_dir() as chroot:
      _path = os.path.join(chroot, 'a/b/c')
      safe_mkdir(_path)
      data_file = os.path.join(_path, 'd.txt')
      with open(data_file, 'w') as fd:
        fd.write('e')

      with self.jarfile() as existing_jarfile:
        with self.jar_task.open_jar(existing_jarfile) as jar:
          jar.write(data_file, 'f/g/h')

        with open_zip(existing_jarfile) as jar:
          self.assert_listing(jar, 'f/', 'f/g/', 'f/g/h')
          self.assertEquals('e', jar.read('f/g/h'))

  def test_update_writestr(self):
    def assert_writestr(path, contents, *entries):
      with self.jarfile() as existing_jarfile:
        with self.jar_task.open_jar(existing_jarfile) as jar:
          jar.writestr(path, contents)

        with open_zip(existing_jarfile) as jar:
          self.assert_listing(jar, *entries)
          self.assertEquals(contents, jar.read(path))

    assert_writestr('a.txt', b'b', 'a.txt')
    assert_writestr('a/b/c.txt', b'd', 'a/', 'a/b/', 'a/b/c.txt')

  def test_overwrite_write(self):
    with temporary_dir() as chroot:
      _path = os.path.join(chroot, 'a/b/c')
      safe_mkdir(_path)
      data_file = os.path.join(_path, 'd.txt')
      with open(data_file, 'w') as fd:
        fd.write('e')

      with self.jarfile() as existing_jarfile:
        with self.jar_task.open_jar(existing_jarfile, overwrite=True) as jar:
          jar.write(data_file, 'f/g/h')

        with open_zip(existing_jarfile) as jar:
          self.assert_listing(jar, 'f/', 'f/g/', 'f/g/h')
          self.assertEquals('e', jar.read('f/g/h'))

  def test_overwrite_writestr(self):
    with self.jarfile() as existing_jarfile:
      with self.jar_task.open_jar(existing_jarfile, overwrite=True) as jar:
        jar.writestr('README', b'42')

      with open_zip(existing_jarfile) as jar:
        self.assert_listing(jar, 'README')
        self.assertEquals('42', jar.read('README'))

  def test_custom_manifest(self):
    contents = b'Manifest-Version: 1.0\r\nCreated-By: test\r\n\r\n'

    with self.jarfile() as existing_jarfile:
      with self.jar_task.open_jar(existing_jarfile, overwrite=True) as jar:
        jar.writestr('README', b'42')

      with open_zip(existing_jarfile) as jar:
        self.assert_listing(jar, 'README')
        self.assertEquals('42', jar.read('README'))
        self.assertNotEqual(contents, jar.read('META-INF/MANIFEST.MF'))

      with self.jar_task.open_jar(existing_jarfile, overwrite=False) as jar:
        jar.writestr('META-INF/MANIFEST.MF', contents)

      with open_zip(existing_jarfile) as jar:
        self.assert_listing(jar, 'README')
        self.assertEquals('42', jar.read('README'))
        self.assertEquals(contents, jar.read('META-INF/MANIFEST.MF'))
