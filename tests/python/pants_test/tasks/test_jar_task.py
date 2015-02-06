# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.jvm.tasks.jar_task import JarTask
from pants.goal.products import MultipleRootedProducts
from pants.util.contextutil import open_zip, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree
from pants_test.jvm.jar_task_test_base import JarTaskTestBase


class BaseJarTaskTest(JarTaskTestBase):
  class TestJarTask(JarTask):
    def execute(self):
      pass

  @classmethod
  def task_type(cls):
    return cls.TestJarTask

  def setUp(self):
    super(BaseJarTaskTest, self).setUp()

    self.workdir = safe_mkdtemp()
    self.jar_task = self.prepare_execute(self.context(), self.workdir)

  def tearDown(self):
    super(BaseJarTaskTest, self).tearDown()

    if self.workdir:
      safe_rmtree(self.workdir)

  @contextmanager
  def jarfile(self):
    with temporary_file() as fd:
      fd.close()
      yield fd.name

  def prepare_jar_task(self, context):
    return self.prepare_execute(context, self.workdir)

  def assert_listing(self, jar, *expected_items):
    self.assertEquals(set(['META-INF/', 'META-INF/MANIFEST.MF']) | set(expected_items),
                      set(jar.namelist()))


class JarTaskTest(BaseJarTaskTest):
  def setUp(self):
    super(JarTaskTest, self).setUp()

    self.jar_task = self.prepare_jar_task(self.context())

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


class JarBuilderTest(BaseJarTaskTest):
  def test_agent_manifest(self):
    self.add_to_build_file('src/java/pants/agents', dedent('''
        java_agent(
          name='fake_agent',
          premain='bob',
          agent_class='fred',
          can_redefine=True,
          can_retransform=True,
          can_set_native_method_prefix=True
        )''').strip())
    java_agent = self.target('src/java/pants/agents:fake_agent')

    context = self.context(target_roots=java_agent)
    jar_task = self.prepare_jar_task(context)

    class_products = context.products.get_data('classes_by_target',
                                               lambda: defaultdict(MultipleRootedProducts))
    java_agent_products = MultipleRootedProducts()
    self.create_file('.pants.d/javac/classes/FakeAgent.class', '0xCAFEBABE')
    java_agent_products.add_rel_paths(os.path.join(self.build_root, '.pants.d/javac/classes'),
                                      ['FakeAgent.class'])
    class_products[java_agent] = java_agent_products

    context.products.safe_create_data('resources_by_target',
                                      lambda: defaultdict(MultipleRootedProducts))

    jar_builder = jar_task.prepare_jar_builder()
    with self.jarfile() as existing_jarfile:
      with jar_task.open_jar(existing_jarfile) as jar:
        jar_builder.add_target(jar, java_agent)

      with open_zip(existing_jarfile) as jar:
        self.assert_listing(jar, 'FakeAgent.class')
        self.assertEqual('0xCAFEBABE', jar.read('FakeAgent.class'))

        manifest = jar.read('META-INF/MANIFEST.MF').strip()
        all_entries = dict(tuple(re.split(r'\s*:\s*', line, 1)) for line in manifest.splitlines())
        expected_entries = {
            'Agent-Class': 'fred',
            'Premain-Class': 'bob',
            'Can-Redefine-Classes': 'true',
            'Can-Retransform-Classes': 'true',
            'Can-Set-Native-Method-Prefix': 'true',
        }
        self.assertEquals(set(expected_entries.items()),
                          set(expected_entries.items()).intersection(set(all_entries.items())))
