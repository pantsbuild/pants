# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.backend.codegen.protobuf.java.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.remote_sources import RemoteSources
from pants.build_graph.resources import Resources
from pants.core_tasks.what_changed import WhatChanged
from pants.goal.workspace import Workspace
from pants.java.jar.jar_dependency import JarDependency
from pants.source.wrapped_globs import Globs, RGlobs
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class BaseWhatChangedTest(ConsoleTaskTestBase):

  @property
  def alias_groups(self):
    return BuildFileAliases(
      # TODO: Use dummy target types here, instead of depending on other backends.
      targets={
        'java_library': JavaLibrary,
        'python_library': TargetMacro.Factory.wrap(PythonLibrary.create, PythonLibrary),
        'jar_library': JarLibrary,
        'unpacked_jars': UnpackedJars,
        'resources': Resources,
        'java_thrift_library': JavaThriftLibrary,
        'java_protobuf_library': JavaProtobufLibrary,
        'python_thrift_library': PythonThriftLibrary,
        'remote_sources': RemoteSources,
      },
      context_aware_object_factories={
        'globs': Globs,
        'rglobs': RGlobs,
      },
      objects={
        'jar': JarDependency,
        'scala_jar': ScalaJarDependency,
      }
    )

  @classmethod
  def task_type(cls):
    return WhatChanged

  def assert_console_output(self, *output, **kwargs):
    options = {'exclude_target_regexp': []}
    if 'options' in kwargs:
      options.update(kwargs['options'])
    kwargs['options'] = options
    super(BaseWhatChangedTest, self).assert_console_output(*output, **kwargs)

  def workspace(self, files=None, parent=None, diffspec=None, diff_files=None):
    class MockWorkspace(Workspace):

      def touched_files(_, p):
        self.assertEqual(parent or 'HEAD', p)
        return files or []

      def changes_in(_, ds):
        self.assertEqual(diffspec, ds)
        return diff_files or []
    return MockWorkspace()


class WhatChangedTestBasic(BaseWhatChangedTest):
  def test_nochanges(self):
    self.assert_console_output(workspace=self.workspace())

  def test_parent(self):
    self.assert_console_output(options={'changes_since': '42'},
                               workspace=self.workspace(parent='42'))

  def test_files(self):
    self.assert_console_output(
      'a/b/c',
      'd',
      'e/f',
      options={'files': True},
      workspace=self.workspace(files=['a/b/c', 'd', 'e/f'])
    )

  def setUp(self):
    super(WhatChangedTestBasic, self).setUp()

    self.add_to_build_file('root/src/py/a', dedent("""
      python_library(
        name='alpha',
        sources=['b/c', 'd'],
        resources=['test.resources']
      )

      jar_library(
        name='beta',
        jars=[
          jar(org='gamma', name='ray', rev='1.137.bruce_banner')
        ]
      )
    """))
    self.create_file('root/src/py/a/b/c', contents='', mode='w')
    self.create_file('root/src/py/a/d', contents='', mode='w')

    self.add_to_build_file('root/src/py/1', dedent("""
      python_library(
        name='numeric',
        sources=['2']
      )
    """))
    self.create_file('root/src/py/1/2', contents='', mode='w')

    self.add_to_build_file('root/src/py/dependency_tree/a', dedent("""
      python_library(
        name='a',
        sources=['a.py'],
      )
    """))
    self.create_file('root/src/py/dependency_tree/a/a.py', contents='', mode='w')

    self.add_to_build_file('root/src/py/dependency_tree/b', dedent("""
      python_library(
        name='b',
        sources=['b.py'],
        dependencies=['root/src/py/dependency_tree/a']
      )
    """))
    self.create_file('root/src/py/dependency_tree/b/b.py', contents='', mode='w')

    self.add_to_build_file('root/src/py/dependency_tree/c', dedent("""
      python_library(
        name='c',
        sources=['c.py'],
        dependencies=['root/src/py/dependency_tree/b']
      )
    """))
    self.create_file('root/src/py/dependency_tree/c/c.py', contents='', mode='w')

    self.add_to_build_file('root/src/thrift', dedent("""
      java_thrift_library(
        name='thrift',
        sources=['a.thrift']
      )

      python_thrift_library(
        name='py-thrift',
        sources=['a.thrift']
      )
    """))
    self.create_file('root/src/thrift/a.thrift', contents='', mode='w')

    self.add_to_build_file('root/src/resources/a', dedent("""
      resources(
        name='a_resources',
        sources=['a.resources']
      )
    """))
    self.create_file('root/src/resources/a/a.resources', contents='', mode='w')

    self.add_to_build_file('root/src/java/a', dedent("""
      java_library(
        name='a_java',
        sources=rglobs("*.java"),
      )
    """))
    self.create_file('root/src/java/a/foo.java', contents='', mode='w')
    self.create_file('root/src/java/a/b/foo.java', contents='', mode='w')

    self.add_to_build_file('root/src/java/b', dedent("""
          java_library(
            name='b_java',
            sources=globs("*.java"),
          )
        """))
    self.create_file('root/src/java/b/foo.java', contents='', mode='w')
    self.create_file('root/src/java/b/b/foo.java', contents='', mode='w')

    self.add_to_build_file('root/3rdparty/BUILD.twitter', dedent("""
      jar_library(
        name='dummy',
        jars=[
          jar(org='foo', name='ray', rev='1.45')
        ])
    """))

    self.add_to_build_file('root/3rdparty/BUILD', dedent("""
      jar_library(
        name='dummy1',
        jars=[
          jar(org='foo1', name='ray', rev='1.45')
        ])
    """))

    # This is a directory that might confuse case insensitive file systems (on macs for example).
    # It should not be treated as a BUILD file.
    self.create_dir('root/scripts/a/build')

    self.add_to_build_file('root/scripts/BUILD', dedent("""
      java_library(
        name='scripts',
        sources=['a/build/scripts.java'],
      )
    """))
    self.create_file('root/scripts/a/build/scripts.java', contents='', mode='w')

    self.add_to_build_file('BUILD.config', dedent("""
      resources(
        name='pants-config',
        sources = globs('pants.ini*')
      )
    """))
    self.create_file('pants.ini', contents='', mode='w')
    self.create_file('pants.ini.backup', contents='', mode='w')


class WhatChangedTest(WhatChangedTestBasic):
  def test_owned(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      'root/src/py/1:numeric',
      workspace=self.workspace(files=['root/src/py/a/b/c', 'root/src/py/a/d', 'root/src/py/1/2'])
    )

  def test_multiply_owned(self):
    self.assert_console_output(
      'root/src/thrift:thrift',
      'root/src/thrift:py-thrift',
      workspace=self.workspace(files=['root/src/thrift/a.thrift'])
    )

  def test_build(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      'root/src/py/a:beta',
      'root/src/py/a:alpha_synthetic_resources',
      workspace=self.workspace(files=['root/src/py/a/BUILD'])
    )

  def test_broken_build_file(self):
    with self.assertRaises(AddressLookupError):
      self.add_to_build_file('root/src/py/a', dedent("""
        //
      """))
      self.assert_console_output(workspace=self.workspace(files=['root/src/py/a/BUILD']))

  def test_resource_changed(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      # Currently, `ParseContext` created objects cannot be synthetic - so these surface as
      # concrete targets. This should be fine for now, since the `resources=` field is
      # deprecated anyway - so this usage pattern is quickly going away.
      'root/src/py/a:alpha_synthetic_resources',
      workspace=self.workspace(files=['root/src/py/a/test.resources'])
    )

  def test_resource_changed_for_java_lib(self):
    self.assert_console_output(
      'root/src/resources/a:a_resources',
      workspace=self.workspace(files=['root/src/resources/a/a.resources'])
    )

  def test_build_sibling(self):
    self.assert_console_output(
      'root/3rdparty:dummy',
      workspace=self.workspace(files=['root/3rdparty/BUILD.twitter'])
    )

  def test_resource_type_error(self):
    self.add_to_build_file('root/src/resources/a1', dedent("""
      java_library(
        name='a1',
        sources=['a1.test'],
        resources=[1]
      )
    """))
    self.assert_console_raises(
      Exception,
      workspace=self.workspace(files=['root/src/resources/a1/a1.test'])
    )

  def test_build_directory(self):
    # This should ensure that a directory named the same as build files does not cause an exception.
    self.assert_console_output(
      'root/scripts:scripts',
      workspace=self.workspace(files=['root/scripts/a/build', 'root/scripts/a/build/scripts.java'])
    )

  def test_fast(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      'root/src/py/1:numeric',
      options={'fast': True},
      workspace=self.workspace(
        files=['root/src/py/a/b/c', 'root/src/py/a/d', 'root/src/py/1/2'],
      ),
    )

  def test_diffspec(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      'root/src/py/1:numeric',
      options={'diffspec': '42'},
      workspace=self.workspace(
        diffspec='42',
        diff_files=['root/src/py/a/b/c', 'root/src/py/a/d', 'root/src/py/1/2'],
      ),
    )

  def test_diffspec_removed_files(self):
    # This file was not created in setup stage.
    file_in_target = 'root/src/java/a/b/c/Foo.java'

    self.assert_console_output(
      'root/src/java/a:a_java',
      options={'diffspec': '42'},
      workspace=self.workspace(
        diffspec='42',
        diff_files=[file_in_target],
      ),
    )

  def test_include_dependees(self):
    self.assert_console_output(
      'root/src/py/dependency_tree/a:a',
      workspace=self.workspace(files=['root/src/py/dependency_tree/a/a.py'])
    )

    self.assert_console_output(
      'root/src/py/dependency_tree/a:a',
      'root/src/py/dependency_tree/b:b',
      options={'include_dependees': 'direct'},
      workspace=self.workspace(files=['root/src/py/dependency_tree/a/a.py'])
    )

    self.assert_console_output(
      'root/src/py/dependency_tree/a:a',
      'root/src/py/dependency_tree/b:b',
      'root/src/py/dependency_tree/c:c',
      options={'include_dependees': 'transitive'},
      workspace=self.workspace(files=['root/src/py/dependency_tree/a/a.py'])
    )

  def test_exclude(self):
    self.assert_console_output(
      'root/src/py/dependency_tree/a:a',
      'root/src/py/dependency_tree/b:b',
      'root/src/py/dependency_tree/c:c',
      options={'include_dependees': 'transitive'},
      workspace=self.workspace(files=['root/src/py/dependency_tree/a/a.py'])
    )

    self.assert_console_output(
      'root/src/py/dependency_tree/a:a',
      'root/src/py/dependency_tree/c:c',
      options={'include_dependees': 'transitive', 'exclude_target_regexp': [':b']},
      workspace=self.workspace(files=['root/src/py/dependency_tree/a/a.py'])
    )

  def test_deferred_sources_new(self):
    self.add_to_build_file('root/proto', dedent("""
      remote_sources(name='unpacked_jars',
        dest=java_protobuf_library,
        sources_target=':external-source',
      )

      unpacked_jars(name='external-source',
        libraries=[':external-source-jars'],
        include_patterns=[
          'com/squareup/testing/**/*.proto',
        ],
      )

      jar_library(name='external-source-jars',
        jars=[
          jar(org='com.squareup.testing.protolib', name='protolib-external-test', rev='0.0.2'),
        ],
      )
    """))

    self.assert_console_output(
      'root/proto:unpacked_jars',
      'root/proto:external-source',
      'root/proto:external-source-jars',
      workspace=self.workspace(files=['root/proto/BUILD'])
    )

  def test_rglobs_in_sources(self):
    self.assert_console_output(
      'root/src/java/a:a_java',
      workspace=self.workspace(files=['root/src/java/a/foo.java'])
    )

    self.assert_console_output(
      'root/src/java/a:a_java',
      workspace=self.workspace(files=['root/src/java/a/b/foo.java'])
    )

  def test_globs_in_sources(self):
    self.assert_console_output(
      'root/src/java/b:b_java',
      workspace=self.workspace(files=['root/src/java/b/foo.java'])
    )

    self.assert_console_output(
      workspace=self.workspace(files=['root/src/java/b/b/foo.java'])
    )

  def test_globs_in_resources_1(self):
    self.add_to_build_file('root/resources', dedent("""
      resources(
        name='resources',
        sources=globs('*')
      )
    """))

    file_in_target = 'root/resources/foo/bar/baz.yml'
    self.create_file(file_in_target, contents='', mode='w')
    self.assert_console_output(
      workspace=self.workspace(files=[file_in_target])
    )

  def test_globs_in_resources_2(self):
    self.add_to_build_file('root/resources', dedent("""
      resources(
        name='resources',
        sources=globs('*')
      )
    """))

    file_in_target = 'root/resources/baz.yml'
    self.create_file(file_in_target, contents='', mode='w')

    self.assert_console_output(
      'root/resources:resources',
      workspace=self.workspace(files=[file_in_target])
    )

  def test_root_config(self):
    self.assert_console_output(
      '//:pants-config',
      workspace=self.workspace(files=['pants.ini'])
    )

  def test_exclude_sources(self):
    self.create_file(relpath='root/resources_exclude/a.png', contents='', mode='w')
    self.create_file(relpath='root/resources_exclude/dir_a/b.png', contents='', mode='w')
    self.create_file(relpath='root/resources_exclude/dir_a/dir_b/c.png', contents='', mode='w')

    # Create a resources target that skips subdir contents and BUILD file.
    self.add_to_build_file('root/resources_exclude/BUILD', dedent("""
      resources(
        name='abc',
        sources=globs('*', exclude=[globs('BUILD*'), globs('*/**')])
      )
    """))

    # In target file touched should be reflected in the changed list.
    self.assert_console_output(
      'root/resources_exclude:abc',
      workspace=self.workspace(files=['root/resources_exclude/a.png'])
    )

    # Changed subdir files should not show up in the changed list.
    self.assert_console_output(
      workspace=self.workspace(files=['root/resources_exclude/dir_a/b.png',
                                      'root/resources_exclude/dir_a/dir_b/c.png'])
    )


class WhatChangedTestWithIgnorePatterns(WhatChangedTestBasic):
  @property
  def build_ignore_patterns(self):
    return ['root/src/py/1']

  def test_build_ignore_patterns(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      workspace=self.workspace(files=['root/src/py/a/b/c', 'root/src/py/a/d', 'root/src/py/1/2'])
    )
