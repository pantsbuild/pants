# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from mock import MagicMock
from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.context import Context
from pants.util.dirutil import safe_rmtree
from pants_test.tasks.task_test_base import TaskTestBase
from twitter.common.collections import OrderedSet

from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen


# TODO (tdesai) Issue-240: Use JvmToolTaskTestBase for ScroogeGenTest
class ScroogeGenTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return ScroogeGen

  @property
  def alias_groups(self):
    return BuildFileAliases(targets={'java_thrift_library': JavaThriftLibrary,
                                     'java_library': JavaLibrary,
                                     'scala_library': ScalaLibrary})

  def setUp(self):
    super(ScroogeGenTest, self).setUp()
    self.task_outdir = os.path.join(self.build_root, 'scrooge', 'gen-java')

  def tearDown(self):
    super(ScroogeGenTest, self).tearDown()
    safe_rmtree(self.task_outdir)

  def test_validate_compiler_configs(self):
    # Set synthetic defaults for the global scope.
    self.set_options_for_scope('thrift-defaults',
                               compiler='unchecked',
                               language='uniform',
                               rpc_style='async')

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='one',
        sources=[],
        dependencies=[],
      )
    '''))

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='two',
        sources=[],
        dependencies=[':one'],
      )
    '''))

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='three',
        sources=[],
        dependencies=[':one'],
        rpc_style='finagle',
      )
    '''))

    target = self.target('test_validate:one')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    task._validate_compiler_configs([self.target('test_validate:one')])
    task._validate_compiler_configs([self.target('test_validate:two')])

    with self.assertRaises(TaskError):
      task._validate_compiler_configs([self.target('test_validate:three')])

  def test_scala(self):
    sources = [os.path.join(self.task_outdir, 'org/pantsbuild/example/Example.scala')]
    self._test_help('scala', 'finagle', ScalaLibrary, sources)

  def test_android(self):
    sources = [os.path.join(self.task_outdir, 'org/pantsbuild/android_example/Example.java')]
    self._test_help('android', 'finagle', JavaLibrary, sources)

  def test_invalid_lang(self):
    with self.assertRaises(TargetDefinitionException):
      self._test_help('not-a-lang', 'finagle', JavaLibrary, [])

  def test_invalid_style(self):
    with self.assertRaises(TargetDefinitionException):
      self._test_help('scala', 'not-a-style', JavaLibrary, [])

  def _test_help(self, language, rpc_style, library_type, sources):
    contents = dedent('''#@namespace android org.pantsbuild.android_example
      namespace java org.pantsbuild.example
      struct Example {
      1: optional i64 number
      }
    ''')

    build_string = dedent('''
      java_thrift_library(name='a',
        sources=['a.thrift'],
        dependencies=[],
        compiler='scrooge',
        language='{language}',
        rpc_style='{rpc_style}',
        strict_deps=True,
      )
    '''.format(language=language, rpc_style=rpc_style))

    self.create_file(relpath='test_smoke/a.thrift', contents=contents)
    self.add_to_build_file('test_smoke', build_string)

    target = self.target('test_smoke:a')
    context = self.context(target_roots=[target])
    task = self.create_task(context)

    task._declares_service = lambda source: False
    task._outdir = MagicMock()
    task._outdir.return_value = self.task_outdir

    task.gen = MagicMock()
    task.gen.return_value = {'test_smoke/a.thrift': sources}

    saved_add_new_target = Context.add_new_target
    try:
      mock = MagicMock()
      Context.add_new_target = mock
      task.execute()

      self.assertEquals(1, mock.call_count)
      _, call_kwargs = mock.call_args
      self.assertEquals(call_kwargs['target_type'], library_type)
      self.assertEquals(call_kwargs['dependencies'], OrderedSet())
      self.assertEquals(call_kwargs['provides'], None)
      self.assertEquals(call_kwargs['sources'], [])
      self.assertEquals(call_kwargs['derived_from'], target)
      self.assertEquals(call_kwargs['strict_deps'], True)

    finally:
      Context.add_new_target = saved_add_new_target
