# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import tempfile

from collections import defaultdict
from contextlib import contextmanager, closing
from textwrap import dedent

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_open, safe_rmtree

from twitter.pants.base.context_utils import create_context
from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.goal.products import MultipleRootedProducts
from twitter.pants.java.jar import open_jar
from twitter.pants.targets.sources import SourceRoot
from twitter.pants.targets import (
    JavaLibrary,
    JavaThriftLibrary,
    Resources,
    ScalaLibrary)
from twitter.pants.tasks.jar_create import is_jvm_library, JarCreate


class JarCreateTestBase(BaseBuildRootTest):
  @staticmethod
  def create_options(**kwargs):
    options = dict(jar_create_outdir=None,
                   jar_create_transitive=None,
                   jar_create_compressed=None,
                   jar_create_classes=None,
                   jar_create_sources=None,
                   jar_create_idl=None,
                   jar_create_javadoc=None)
    options.update(**kwargs)
    return options

  @classmethod
  def create_files(cls, path, files):
    for f in files:
      cls.create_file(os.path.join(path, f), contents=f)

  @classmethod
  def library(cls, path, target_type, name, sources):
    cls.create_files(path, sources)

    cls.create_target(path, dedent('''
      %(target_type)s(name='%(name)s',
        sources=[%(sources)s],
      )
    ''' % dict(target_type=target_type, name=name, sources=repr(sources or []))))

    return cls.target('%s:%s' % (path, name))

  @classmethod
  def resources(cls, path, name, *sources):
    return cls.library(path, 'resources', name, sources)


class JarCreateMiscTest(JarCreateTestBase):
  def test_jar_create_init(self):
    ini = dedent("""
          [DEFAULT]
          pants_workdir: /tmp/pants.d
          pants_supportdir: /tmp/build-support
          """).strip()

    jar_create = JarCreate(create_context(config=ini, options=self.create_options()))
    self.assertEquals(jar_create._output_dir, '/tmp/pants.d/jars')
    self.assertEquals(jar_create.confs, ['default'])

  def test_resources_with_scala_java_files(self):
    for ftype in ('java', 'scala'):
      target = self.resources(os.path.join('project', ftype),
                              'target_%s' % ftype,
                              'hello.%s' % ftype)
      self.assertFalse(is_jvm_library(target))


class JarCreateExecuteTest(JarCreateTestBase):
  @classmethod
  def library_with_resources(cls, path, target_type, name, sources, resources=None):
    cls.create_files(path, sources)

    cls.create_target(path, dedent('''
      %(target_type)s(name='%(name)s',
        sources=[%(sources)s],
        %(resources)s
      )
    ''' % dict(target_type=target_type,
               name=name,
               sources=repr(sources or []),
               resources=('resources=pants("%s")' % resources if resources else ''))))

    return cls.target('%s:%s' % (path, name))

  @classmethod
  def java_library(cls, path, name, sources, resources=None):
    return cls.library_with_resources(path, 'java_library', name, sources, resources=resources)

  @classmethod
  def scala_library(cls, path, name, sources, resources=None):
    return cls.library_with_resources(path, 'scala_library', name, sources, resources=resources)

  @classmethod
  def java_thrift_library(cls, path, name, *sources):
    return cls.library(path, 'java_thrift_library', name, sources)

  @classmethod
  def setUpClass(cls):
    super(JarCreateExecuteTest, cls).setUpClass()

    def get_source_root_fs_path(path):
        return os.path.realpath(os.path.join(cls.build_root, path))

    SourceRoot.register(get_source_root_fs_path('src/resources'), Resources)
    SourceRoot.register(get_source_root_fs_path('src/java'), JavaLibrary)
    SourceRoot.register(get_source_root_fs_path('src/scala'), ScalaLibrary)
    SourceRoot.register(get_source_root_fs_path('src/thrift'), JavaThriftLibrary)

    cls.res = cls.resources('src/resources/com/twitter', 'spam', 'r.txt')
    cls.jl = cls.java_library('src/java/com/twitter', 'foo', ['a.java'],
                              resources='src/resources/com/twitter:spam')
    cls.sl = cls.scala_library('src/scala/com/twitter', 'bar', ['c.scala'])
    cls.jtl = cls.java_thrift_library('src/thrift/com/twitter', 'baz', 'd.thrift')

  def setUp(self):
    super(JarCreateExecuteTest, self).setUp()
    self.jar_outdir = tempfile.mkdtemp()

  def tearDown(self):
    super(JarCreateExecuteTest, self).tearDown()
    safe_rmtree(self.jar_outdir)

  def context(self, config='', **options):
    opts = dict(jar_create_outdir=self.jar_outdir)
    opts.update(**options)
    return create_context(config=config, options=self.create_options(**opts),
                          target_roots=[self.jl, self.sl, self.jtl])

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
          JarCreate(context).execute(context.targets())
          if empty:
            self.assertTrue(context.products.get('jars').empty())
          else:
            self.assert_jar_contents(context, 'jars', self.jl,
                                     'a.class', 'b.class', 'r.txt.transformed')
            self.assert_jar_contents(context, 'jars', self.sl, 'c.class')

  def test_classfile_jar_required(self):
    context = self.context()
    context.products.require('jars')
    self.assert_classfile_jar_contents(context)

  def test_classfile_jar_flagged(self):
    self.assert_classfile_jar_contents(self.context(jar_create_classes=True))

  def test_classfile_jar_not_required(self):
    self.assert_classfile_jar_contents(self.context(), empty=True)

  def assert_source_jar_contents(self, context, empty=False):
    JarCreate(context).execute(context.targets())

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
        JarCreate(context, **kwargs).execute(context.targets())

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

  def test_javadoc_jar_constructor_required(self):
    self.assert_javadoc_jar_contents(self.context(), jar_javadoc=True)

  def test_javadoc_jar_not_required(self):
    self.assert_javadoc_jar_contents(self.context(), empty=True, jar_javadoc=False)

