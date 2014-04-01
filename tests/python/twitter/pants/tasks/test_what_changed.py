# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.base.target import TargetDefinitionException
from pants.tasks.test_base import ConsoleTaskTest
from pants.tasks.what_changed import WhatChanged, Workspace


class BaseWhatChangedTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return WhatChanged

  def workspace(self, files=None, parent=None):
    class MockWorkspace(Workspace):
      @staticmethod
      def touched_files(p):
        self.assertEqual(parent or 'HEAD', p)
        return files or []
    return MockWorkspace()


class WhatChangedTestBasic(BaseWhatChangedTest):
  def test_nochanges(self):
    self.assert_console_output(workspace=self.workspace())

  def test_parent(self):
    self.assert_console_output(args=['--test-parent=42'], workspace=self.workspace(parent='42'))

  def test_files(self):
    self.assert_console_output(
      'a/b/c',
      'd',
      'e/f',
      args=['--test-files'],
      workspace=self.workspace(files=['a/b/c', 'd', 'e/f'])
    )


class WhatChangedTest(BaseWhatChangedTest):
  @classmethod
  def setUpClass(cls):
    super(WhatChangedTest, cls).setUpClass()

    cls.create_target('root', dedent('''
      source_root('src/py', python_library)
      source_root('resources/a1', resources)
    '''))

    cls.create_target('root/src/py/a', dedent('''
      python_library(
        name='alpha',
        sources=['b/c', 'd'],
        resources=['test.resources']
      )

      jar_library(
        name='beta',
        dependencies=[
          jar(org='gamma', name='ray', rev='1.137.bruce_banner')
        ]
      )
    '''))

    cls.create_target('root/src/py/1', dedent('''
      python_library(
        name='numeric',
        sources=['2']
      )
    '''))

    cls.create_target('root/src/thrift', dedent('''
      java_thrift_library(
        name='thrift',
        sources=['a.thrift']
      )

      python_thrift_library(
        name='py-thrift',
        sources=['a.thrift']
      )
    '''))

    cls.create_target('root/resources/a', dedent('''
      resources(
        name='a_resources',
        sources=['a.resources']
      )
    '''))

    cls.create_target('root/src/java/a', dedent('''
      java_library(
        name='a_java',
        sources=['a.java'],
        resources=[pants('root/resources/a:a_resources')]
      )
    '''))

    cls.create_target('root/3rdparty/BUILD.twitter', dedent('''
      jar_library(
        name='dummy',
        dependencies=[
          jar(org='foo', name='ray', rev='1.45')
        ])
    '''))

    cls.create_target('root/3rdparty/BUILD', dedent('''
      jar_library(
        name='dummy1',
        dependencies=[
          jar(org='foo1', name='ray', rev='1.45')
        ])
    '''))

  def test_owned(self):
    self.assert_console_output(
      'root/src/py/a/BUILD:alpha',
      'root/src/py/1/BUILD:numeric',
      workspace=self.workspace(files=['root/src/py/a/b/c', 'root/src/py/a/d', 'root/src/py/1/2'])
    )

  def test_multiply_owned(self):
    self.assert_console_output(
      'root/src/thrift/BUILD:thrift',
      'root/src/thrift/BUILD:py-thrift',
      workspace=self.workspace(files=['root/src/thrift/a.thrift'])
    )

  def test_build(self):
    self.assert_console_output(
      'root/src/py/a/BUILD:alpha',
      'root/src/py/a/BUILD:beta',
      workspace=self.workspace(files=['root/src/py/a/BUILD'])
    )

  def test_resource_changed(self):
    self.assert_console_output(
      'root/src/py/a/BUILD:alpha',
      workspace=self.workspace(files=['root/src/py/a/test.resources'])
    )

  def test_resource_changed_for_java_lib(self):
    self.assert_console_output(
      'root/resources/a/BUILD:a_resources',
      workspace=self.workspace(files=['root/resources/a/a.resources'])
    )

  def test_build_sibling(self):
    self.assert_console_output(
      'root/3rdparty/BUILD.twitter:dummy',
      workspace=self.workspace(files=['root/3rdparty/BUILD.twitter'])
    )

  def test_resource_type_error(self):
    self.create_target('root/resources/a1', dedent('''
      java_library(
        name='a1',
        sources=['a1.test'],
        resources=[1]
      )
    '''))
    self.assert_console_raises(
      TargetDefinitionException,
      workspace=self.workspace(files=['root/resources/a1/a1.test'])
    )
