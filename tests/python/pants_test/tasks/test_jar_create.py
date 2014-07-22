# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from contextlib import closing, contextmanager
import os
from textwrap import dedent

from twitter.common.contextutil import open_zip, temporary_dir

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jar_create import JarCreate, is_jvm_library
from pants.base.source_root import SourceRoot
from pants.goal.products import MultipleRootedProducts
from pants.util.dirutil import safe_open
from pants_test.base.context_utils import create_context
from pants_test.jvm.jar_task_test_base import JarTaskTestBase


class JarCreateTestBase(JarTaskTestBase):
  def create_options(self, **kwargs):
    options = dict(jar_create_transitive=True,
                   jar_create_compressed=False,
                   jar_create_classes=False,
                   jar_create_sources=False,
                   jar_create_javadoc=False)
    options.update(**kwargs)
    return super(JarCreateTestBase, self).create_options(**options)


class JarCreateMiscTest(JarCreateTestBase):
  def test_jar_create_init(self):
    ini = dedent("""
          [DEFAULT]
          pants_supportdir: /tmp/build-support
          """).strip()

    JarCreate(create_context(config=ini,
                             options=self.create_options(),
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser),
              '/tmp/workdir')

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
    self.add_to_build_file(path, dedent('''
          jvm_binary(name=%(name)r,
            source=%(source)r,
            resources=[%(resources)r],
          )
        ''' % dict(name=name, source=source, resources=resources)))
    return self.target('%s:%s' % (path, name))

  def java_thrift_library(self, path, name, *sources):
    return self.create_library(path, 'java_thrift_library', name, sources)

  def setUp(self):
    super(JarCreateExecuteTest, self).setUp()

    def get_source_root_fs_path(path):
      return os.path.realpath(os.path.join(self.build_root, path))

    SourceRoot.register(get_source_root_fs_path('src/resources'), Resources)
    SourceRoot.register(get_source_root_fs_path('src/java'), JavaLibrary, JvmBinary)
    SourceRoot.register(get_source_root_fs_path('src/scala'), ScalaLibrary)
    SourceRoot.register(get_source_root_fs_path('src/thrift'), JavaThriftLibrary)

    self.res = self.create_resources('src/resources/com/twitter', 'spam', 'r.txt')
    self.jl = self.java_library('src/java/com/twitter', 'foo', ['a.java'],
                                resources='src/resources/com/twitter:spam')
    self.sl = self.scala_library('src/scala/com/twitter', 'bar', ['c.scala'])
    self.jtl = self.java_thrift_library('src/thrift/com/twitter', 'baz', 'd.thrift')
    self.java_lib_foo = self.java_library('src/java/com/twitter/foo', 'java_foo', ['java_foo.java'])
    self.scala_lib = self.scala_library('src/scala/com/twitter/foo',
                                        'scala_foo',
                                        ['scala_foo.scala'],
                                        java_sources=['src/java/com/twitter/foo:java_foo'])
    self.binary = self.jvm_binary('src/java/com/twitter/baz', 'baz', source='b.java',
                                  resources='src/resources/com/twitter:spam')

  def context(self, config='', **options):
    return create_context(config=self.config(overrides=config),
                          options=self.create_options(**options),
                          build_graph=self.build_graph,
                          build_file_parser=self.build_file_parser,
                          target_roots=[self.jl, self.sl, self.binary, self.jtl, self.scala_lib])

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
      with open_zip(os.path.join(basedir, jars[0])) as jar:
        self.assertEqual(['META-INF/', 'META-INF/MANIFEST.MF'] + list(contents), jar.namelist())
        for content in contents:
          if not content.endswith('/'):
            with closing(jar.open(content)) as fp:
              self.assertEqual(os.path.basename(content), fp.read())

  def test_classfile_jar_contents(self):
    context = self.context()
    with self.add_data(context, 'classes_by_target', self.jl, 'a.class', 'b.class'):
      with self.add_data(context, 'classes_by_target', self.sl, 'c.class'):
        with self.add_data(context, 'classes_by_target', self.binary, 'b.class'):
          with self.add_data(context, 'resources_by_target', self.res, 'r.txt.transformed'):
            with self.add_data(context, 'classes_by_target', self.scala_lib, 'scala_foo.class',
                               'java_foo.class'):
              self.execute(context, JarCreate)

              self.assert_jar_contents(context, 'jars', self.jl,
                                        'a.class', 'b.class', 'r.txt.transformed')
              self.assert_jar_contents(context, 'jars', self.sl, 'c.class')
              self.assert_jar_contents(context, 'jars', self.binary,
                                        'b.class', 'r.txt.transformed')
              self.assert_jar_contents(context, 'jars', self.scala_lib, 'scala_foo.class',
                                        'java_foo.class')
