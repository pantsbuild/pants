# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from collections import defaultdict
from contextlib import closing, contextmanager
from textwrap import dedent

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_open

from pants.goal.products import MultipleRootedProducts
from pants.java.jar import open_jar
from pants.targets.java_library import JavaLibrary
from pants.targets.java_thrift_library import JavaThriftLibrary
from pants.targets.resources import Resources
from pants.targets.scala_library import ScalaLibrary
from pants.targets.sources import SourceRoot
from pants.tasks.jar_create import JarCreate, is_jvm_library
from pants_test.base_build_root_test import BaseBuildRootTest
from pants_test.base.context_utils import create_context


class JarCreateTestBase(BaseBuildRootTest):
  @staticmethod
  def create_options(**kwargs):
    options = dict(jar_create_transitive=None,
                   jar_create_compressed=None,
                   jar_create_classes=None,
                   jar_create_sources=None,
                   jar_create_idl=None,
                   jar_create_javadoc=None)
    options.update(**kwargs)
    return options


class JarCreateMiscTest(JarCreateTestBase):
  def test_jar_create_init(self):
    ini = dedent("""
          [DEFAULT]
          pants_supportdir: /tmp/build-support
          """).strip()

    JarCreate(create_context(config=ini, options=self.create_options()), '/tmp/workdir')

  def test_resources_with_scala_java_files(self):
    for ftype in ('java', 'scala'):
      target = self.create_resources(os.path.join('project', ftype),
                              'target_%s' % ftype,
                              'hello.%s' % ftype)
      self.assertFalse(is_jvm_library(target))


class JarCreateExecuteTest(JarCreateTestBase):
  @classmethod
  def java_library(cls, path, name, sources, **kwargs):
    return cls.create_library(path, 'java_library', name, sources, **kwargs)

  @classmethod
  def scala_library(cls, path, name, sources, **kwargs):
    return cls.create_library(path, 'scala_library', name, sources, **kwargs)

  @classmethod
  def java_thrift_library(cls, path, name, *sources):
    return cls.create_library(path, 'java_thrift_library', name, sources)

  @classmethod
  def setUpClass(cls):
    super(JarCreateExecuteTest, cls).setUpClass()
    cls.create_target('build-support/ivy',
                      dedent('''
                         repo(name = 'ivy',
                              url = 'https://art.twitter.biz/',
                              push_db = 'dummy.pushdb')
                       '''))

    def get_source_root_fs_path(path):
        return os.path.realpath(os.path.join(cls.build_root, path))

    SourceRoot.register(get_source_root_fs_path('src/resources'), Resources)
    SourceRoot.register(get_source_root_fs_path('src/java'), JavaLibrary)
    SourceRoot.register(get_source_root_fs_path('src/scala'), ScalaLibrary)
    SourceRoot.register(get_source_root_fs_path('src/thrift'), JavaThriftLibrary)

    cls.res = cls.create_resources('src/resources/com/twitter', 'spam', 'r.txt')
    cls.jl = cls.java_library('src/java/com/twitter', 'foo', ['a.java'],
                              resources='src/resources/com/twitter:spam')
    cls.sl = cls.scala_library('src/scala/com/twitter', 'bar', ['c.scala'])
    cls.jtl = cls.java_thrift_library('src/thrift/com/twitter', 'baz', 'd.thrift')
    cls.java_lib_foo= cls.java_library('src/java/com/twitter/foo', 'java_foo', ['java_foo.java'])
    cls.scala_lib = cls.scala_library('src/scala/com/twitter/foo',
                                      'scala_foo',
                                      ['scala_foo.scala'],
                                      provides=True,
                                      java_sources=['src/java/com/twitter/foo:java_foo'])

  def context(self, config='', **options):
    return create_context(config=config, options=self.create_options(**options),
                          target_roots=[self.jl, self.sl, self.jtl, self.scala_lib])

  @contextmanager
  def add_products(self, context, product_type, target, *products):
    product_mapping = context.products.get(product_type)
    with temporary_dir() as outdir:
      def create_product(product):
        with safe_open(os.path.join(outdir, product), mode='w') as fp:
          fp.write(product)
        return product
      product_mapping.add(target, outdir, map(create_product, products))
      yield temporary_dir

  @contextmanager
  def add_data(self, context, data_type, target, *products):
    make_products = lambda: defaultdict(MultipleRootedProducts)
    data_by_target = context.products.get_data(data_type, make_products)
    with temporary_dir() as outdir:
      def create_product(product):
        abspath = os.path.join(outdir, product)
        with safe_open(abspath, mode='w') as fp:
          fp.write(product)
        return abspath
      data_by_target[target].add_abs_paths(outdir, map(create_product, products))
      yield temporary_dir

  def assert_jar_contents(self, context, product_type, target, *contents):
    jar_mapping = context.products.get(product_type).get(target)
    self.assertEqual(1, len(jar_mapping))
    for basedir, jars in jar_mapping.items():
      self.assertEqual(1, len(jars))
      with open_jar(os.path.join(basedir, jars[0])) as jar:
        self.assertEqual(list(contents), jar.namelist())
        for content in contents:
          if not content.endswith('/'):
            with closing(jar.open(content)) as fp:
              self.assertEqual(os.path.basename(content), fp.read())

  def assert_classfile_jar_contents(self, context, empty=False):
    with self.add_data(context, 'classes_by_target', self.jl, 'a.class', 'b.class'):
      with self.add_data(context, 'classes_by_target', self.sl, 'c.class'):
        with self.add_data(context, 'resources_by_target', self.res, 'r.txt.transformed'):
          with self.add_data(context, 'classes_by_target', self.scala_lib, 'scala_foo.class',
                             'java_foo.class'):
            with temporary_dir() as workdir:
              JarCreate(context, workdir).execute(context.targets())
              if empty:
                self.assertTrue(context.products.get('jars').empty())
              else:
                self.assert_jar_contents(context, 'jars', self.jl,
                                        'a.class', 'b.class', 'r.txt.transformed')
                self.assert_jar_contents(context, 'jars', self.sl, 'c.class')
                self.assert_jar_contents(context, 'jars', self.scala_lib, 'scala_foo.class',
                                         'java_foo.class')

  def test_classfile_jar_required(self):
    context = self.context()
    context.products.require('jars')
    self.assert_classfile_jar_contents(context)

  def test_classfile_jar_flagged(self):
    self.assert_classfile_jar_contents(self.context(jar_create_classes=True))

  def test_classfile_jar_not_required(self):
    self.assert_classfile_jar_contents(self.context(), empty=True)

  def assert_source_jar_contents(self, context, empty=False):
    with temporary_dir() as workdir:
      JarCreate(context, workdir).execute(context.targets())

      if empty:
        self.assertTrue(context.products.get('source_jars').empty())
      else:
        self.assert_jar_contents(context, 'source_jars', self.jl,
                                 'com/', 'com/twitter/', 'com/twitter/a.java', 'com/twitter/r.txt')
        self.assert_jar_contents(context, 'source_jars', self.sl,
                                 'com/', 'com/twitter/', 'com/twitter/c.scala')

  def test_source_jar_required(self):
    context = self.context()
    context.products.require('source_jars')
    self.assert_source_jar_contents(context)

  def test_source_jar_flagged(self):
    self.assert_source_jar_contents(self.context(jar_create_sources=True))

  def test_source_jar_not_required(self):
    self.assert_source_jar_contents(self.context(), empty=True)

  def assert_javadoc_jar_contents(self, context, empty=False, **kwargs):
    with self.add_products(context, 'javadoc', self.jl, 'a.html', 'b.html'):
      with self.add_products(context, 'scaladoc', self.sl, 'c.html'):
        with temporary_dir() as workdir:
          JarCreate(context, workdir, **kwargs).execute(context.targets())

          if empty:
            self.assertTrue(context.products.get('javadoc_jars').empty())
          else:
            self.assert_jar_contents(context, 'javadoc_jars', self.jl, 'a.html', 'b.html')
            self.assert_jar_contents(context, 'javadoc_jars', self.sl, 'c.html')

  def test_javadoc_jar_required(self):
    context = self.context()
    context.products.require('javadoc_jars')
    self.assert_javadoc_jar_contents(context)

  def test_javadoc_jar_flagged(self):
    self.assert_javadoc_jar_contents(self.context(jar_create_javadoc=True))
