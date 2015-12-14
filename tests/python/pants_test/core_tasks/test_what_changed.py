# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.core.from_target import FromTarget
from pants.backend.core.wrapped_globs import Globs, RGlobs
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.core_tasks.what_changed import WhatChanged
from pants.goal.workspace import Workspace
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class BaseWhatChangedTest(ConsoleTaskTestBase):

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'java_library': JavaLibrary,
        'python_library': PythonLibrary,
        'jar_library': JarLibrary,
        'unpacked_jars': UnpackedJars,
        'resources': Resources,
        'java_thrift_library': JavaThriftLibrary,
        'java_protobuf_library': JavaProtobufLibrary,
        'python_thrift_library': PythonThriftLibrary,
      },
      context_aware_object_factories={
        'globs': Globs.factory,
        'rglobs': RGlobs.factory,
        'from_target': FromTarget,
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
    options = {'spec_excludes': [], 'exclude_target_regexp': []}
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


class WhatChangedTest(BaseWhatChangedTest):

  def setUp(self):
    super(WhatChangedTest, self).setUp()

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

    self.add_to_build_file('root/src/py/1', dedent("""
      python_library(
        name='numeric',
        sources=['2']
      )
    """))

    self.add_to_build_file('root/src/py/dependency_tree/a', dedent("""
      python_library(
        name='a',
        sources=['a.py'],
      )
    """))

    self.add_to_build_file('root/src/py/dependency_tree/b', dedent("""
      python_library(
        name='b',
        sources=['b.py'],
        dependencies=['root/src/py/dependency_tree/a']
      )
    """))

    self.add_to_build_file('root/src/py/dependency_tree/c', dedent("""
      python_library(
        name='c',
        sources=['c.py'],
        dependencies=['root/src/py/dependency_tree/b']
      )
    """))

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

    self.add_to_build_file('root/src/resources/a', dedent("""
      resources(
        name='a_resources',
        sources=['a.resources']
      )
    """))

    self.add_to_build_file('root/src/java/a', dedent("""
      java_library(
        name='a_java',
        sources=rglobs("*.java"),
      )
    """))

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

    self.add_to_build_file('BUILD.config', dedent("""
      resources(
        name='pants-config',
        sources = globs('pants.ini*')
      )
    """))

  def test_spec_excludes(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
      options={'spec_excludes': 'root/src/py/1'},
      workspace=self.workspace(files=['root/src/py/a/b/c', 'root/src/py/a/d'])
    )

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
      workspace=self.workspace(files=['root/src/py/a/BUILD'])
    )

  def test_resource_changed(self):
    self.assert_console_output(
      'root/src/py/a:alpha',
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
    self.assert_console_output(
      'root/src/java/a:a_java',
      options={'diffspec': '42'},
      workspace=self.workspace(
        diffspec='42',
        diff_files=['root/src/java/a/b/c/Foo.java'],
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

  def test_deferred_sources(self):
    self.add_to_build_file('root/proto', dedent("""
      java_protobuf_library(name='unpacked_jars',
        sources=from_target(':external-source'),
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

  def test_globs_in_resources(self):
    self.add_to_build_file('root/resources', dedent("""
      resources(
        name='resources',
        sources=globs('*')
      )
    """))

    self.assert_console_output(
      'root/resources:resources',
      workspace=self.workspace(files=['root/resources/foo/bar/baz.yml'])
    )

  def test_root_config(self):
    self.assert_console_output(
      '//:pants-config',
      workspace=self.workspace(files=['pants.ini'])
    )
