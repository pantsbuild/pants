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

from six.moves import range
from twitter.common.collections import maybe_list

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
  MAX_SUBPROC_ARGS = 50

  def setUp(self):
    super(JarTaskTest, self).setUp()
    self.set_options(max_subprocess_args=self.MAX_SUBPROC_ARGS)
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

  def test_classpath(self):
    def manifest_content(classpath):
      return (b'Manifest-Version: 1.0\r\n' +
              b'Class-Path: {}\r\n' +
              b'Created-By: com.twitter.common.jar.tool.JarBuilder\r\n\r\n').format(
                ' '.join(maybe_list(classpath)))

    def assert_classpath(classpath):
      with self.jarfile() as existing_jarfile:
        # Note for -classpath, there is no update, it's already overwriting.
        # To verify this, first add a random classpath, and verify it's overwritten by
        # the supplied classpath value.
        with self.jar_task.open_jar(existing_jarfile) as jar:
          jar.classpath('something_should_be_overwritten.jar')

        with self.jar_task.open_jar(existing_jarfile) as jar:
          jar.classpath(classpath)

        with open_zip(existing_jarfile) as jar:
          self.assertEqual(manifest_content(classpath), jar.read('META-INF/MANIFEST.MF'))

    assert_classpath('a.jar')
    assert_classpath(['a.jar', 'b.jar'])

  def test_update_jars(self):
    with self.jarfile() as main_jar:
      with self.jarfile() as included_jar:
        with self.jar_task.open_jar(main_jar) as jar:
          jar.writestr('a/b', b'c')

        with self.jar_task.open_jar(included_jar) as jar:
          jar.writestr('e/f', b'g')

        with self.jar_task.open_jar(main_jar) as jar:
          jar.writejar(included_jar)

        with open_zip(main_jar) as jar:
          self.assert_listing(jar, 'a/', 'a/b', 'e/', 'e/f')

  def test_overwrite_jars(self):
    with self.jarfile() as main_jar:
      with self.jarfile() as included_jar:
        with self.jar_task.open_jar(main_jar) as jar:
          jar.writestr('a/b', b'c')

        with self.jar_task.open_jar(included_jar) as jar:
          jar.writestr('e/f', b'g')

        # Create lots of included jars (even though they're all the same)
        # so the -jars argument to jar-tool will exceed max_args limit thus
        # switch to @argfile calling style.
        with self.jar_task.open_jar(main_jar, overwrite=True) as jar:
          for i in range(self.MAX_SUBPROC_ARGS + 1):
            jar.writejar(included_jar)

        with open_zip(main_jar) as jar:
          self.assert_listing(jar, 'e/', 'e/f')


class JarBuilderTest(BaseJarTaskTest):

  def setUp(self):
    super(JarBuilderTest, self).setUp()
    self.set_options(max_subprocess_args=100)

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

    context = self.context(target_roots=[java_agent])
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

    with self.jarfile() as existing_jarfile:
      with jar_task.open_jar(existing_jarfile) as jar:
        jar_builder = jar_task.create_jar_builder(jar)
        jar_builder.add_target(java_agent)

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
