# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import closing
from textwrap import dedent

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jar_create import JarCreate, is_jvm_library
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.util.contextutil import open_zip
from pants_test.jvm.jar_task_test_base import JarTaskTestBase
from pants_test.tasks.task_test_base import ensure_cached


class JarCreateTestBase(JarTaskTestBase):

  @classmethod
  def task_type(cls):
    return JarCreate

  @property
  def alias_groups(self):
    return super(JarCreateTestBase, self).alias_groups.merge(BuildFileAliases(
      targets={
        'java_library': JavaLibrary,
        'java_thrift_library': JavaThriftLibrary,
        'jvm_binary': JvmBinary,
        'resources': Resources,
        'scala_library': ScalaLibrary,
      },
    ))

  def setUp(self):
    super(JarCreateTestBase, self).setUp()
    self.set_options(compressed=False, pants_bootstrapdir='~/.cache/pants', max_subprocess_args=100)


class JarCreateMiscTest(JarCreateTestBase):

  def test_jar_create_init(self):
    self.create_task(self.context(), '/tmp/workdir')

  def test_resources_with_scala_java_files(self):
    for ftype in ('java', 'scala'):
      target = self.create_resources(os.path.join('project', ftype),
                                     'target_%s' % ftype,
                                     'hello.%s' % ftype)
      self.assertFalse(is_jvm_library(target))


class JarCreateExecuteTest(JarCreateTestBase):

  def java_library(self, path, name, sources, **kwargs):
    return self.create_library(path, 'java_library', name, sources, **kwargs)

  def scala_library(self, path, name, sources, **kwargs):
    return self.create_library(path, 'scala_library', name, sources, **kwargs)

  def jvm_binary(self, path, name, source=None, resources=None):
    self.create_files(path, [source])
    self.add_to_build_file(path, dedent("""
          jvm_binary(name=%(name)r,
            source=%(source)r,
            resources=[%(resources)r],
          )
        """ % dict(name=name, source=source, resources=resources)))
    return self.target('%s:%s' % (path, name))

  def java_thrift_library(self, path, name, *sources):
    return self.create_library(path, 'java_thrift_library', name, sources)

  def setUp(self):
    super(JarCreateExecuteTest, self).setUp()

    def test_path(path):
      return os.path.join(self.__class__.__name__, path)

    # This is hacky: Creating a scala_library below requires Subsystem initialization,
    # which we must force by this call to the superclass context() (note that can't call our own
    # context() because it expects the scala_library to already exist). The test methods themselves
    # then call self.context() again to get hold of a context, which will superfluously (but
    # harmlessly) re-initialize Subsystem.
    # TODO: Fix this hack by separating option setup from context setup in the test sequence.
    super(JarCreateExecuteTest, self).context()

    self.res = self.create_resources(test_path('src/resources/com/twitter'), 'spam', 'r.txt')
    self.jl = self.java_library(test_path('src/java/com/twitter'), 'foo', ['a.java'],
                                resources=test_path('src/resources/com/twitter:spam'))
    self.sl = self.scala_library(test_path('src/scala/com/twitter'), 'bar', ['c.scala'])
    self.jtl = self.java_thrift_library(test_path('src/thrift/com/twitter'), 'baz', 'd.thrift')
    self.java_lib_foo = self.java_library(test_path('src/java/com/twitter/foo'),
                                          'java_foo',
                                          ['java_foo.java'])
    self.scala_lib = self.scala_library(test_path('src/scala/com/twitter/foo'),
                                        'scala_foo',
                                        ['scala_foo.scala'],
                                        java_sources=[
                                          test_path('src/java/com/twitter/foo:java_foo')])
    self.binary = self.jvm_binary(test_path('src/java/com/twitter/baz'), 'baz', source='b.java',
                                  resources=test_path('src/resources/com/twitter:spam'))
    self.empty_sl = self.scala_library(test_path('src/scala/com/foo'), 'foo', ['dupe.scala'])

  def context(self, **kwargs):
    return super(JarCreateExecuteTest, self).context(
      target_roots=[self.jl, self.sl, self.binary, self.jtl, self.scala_lib, self.empty_sl],
      **kwargs)

  def assert_jar_contents(self, context, product_type, target, *contents):
    """Contents is a list of lists representing contents from particular classpath entries.

    Ordering across classpath entries is guaranteed, but not within classpath entries.
    """
    jar_mapping = context.products.get(product_type).get(target)
    self.assertEqual(1, len(jar_mapping))
    for basedir, jars in jar_mapping.items():
      self.assertEqual(1, len(jars))
      with open_zip(os.path.join(basedir, jars[0])) as jar:
        actual_iter = iter(jar.namelist())
        self.assertPrefixEqual(['META-INF/', 'META-INF/MANIFEST.MF'], actual_iter)
        for content_set in list(contents):
          self.assertUnorderedPrefixEqual(content_set, actual_iter)
          for content in content_set:
            if not content.endswith('/'):
              with closing(jar.open(content)) as fp:
                self.assertEqual(os.path.basename(content), fp.read())

  @ensure_cached(JarCreate)
  def test_classfile_jar_contents(self):
    context = self.context()

    def idict(*args):
      return {a: a for a in args}

    self.add_to_runtime_classpath(context, self.jl, idict('a.class', 'b.class'))
    self.add_to_runtime_classpath(context, self.sl, idict('c.class'))
    self.add_to_runtime_classpath(context, self.binary, idict('b.class'))
    self.add_to_runtime_classpath(context, self.scala_lib, idict('scala_foo.class', 'java_foo.class'))
    self.add_to_runtime_classpath(context, self.res, idict('r.txt.transformed'))

    self.execute(context)

    self.assert_jar_contents(context, 'jars', self.jl, ['a.class', 'b.class'], ['r.txt.transformed'])
    self.assert_jar_contents(context, 'jars', self.sl, ['c.class'])
    self.assert_jar_contents(context, 'jars', self.binary, ['b.class'], ['r.txt.transformed'])
    self.assert_jar_contents(context, 'jars', self.scala_lib, ['scala_foo.class', 'java_foo.class'])

  def test_empty_scala_files(self):
    context = self.context()

    # Create classpaths for other libraries, in order to initialize the product.
    self.add_to_runtime_classpath(context, self.sl, {})
    self.add_to_runtime_classpath(context, self.res, {'r.txt.transformed': ''})

    self.execute(context)

    self.assertFalse(context.products.get('jars').has(self.empty_sl))
