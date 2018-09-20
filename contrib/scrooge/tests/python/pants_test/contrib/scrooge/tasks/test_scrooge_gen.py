# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from mock import MagicMock
from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.context import Context
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase
from twitter.common.collections import OrderedSet

from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen


GEN_ADAPT = '--gen-adapt'


class ScroogeGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return ScroogeGen

  @classmethod
  def alias_groups(cls):
    return super(ScroogeGenTest, cls).alias_groups().merge(
      BuildFileAliases(targets={'java_thrift_library': JavaThriftLibrary,
                                'java_library': JavaLibrary,
                                'scala_library': ScalaLibrary}))

  def test_validate_compiler_configs(self):
    # Set synthetic defaults for the global scope.
    self.set_options_for_scope('thrift-defaults',
                               compiler='unchecked',
                               language='uniform',
                               service_deps='service_deps',
                               structs_deps='structs_deps')

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

    target = self.target('test_validate:one')
    context = self.context(target_roots=[target])
    task = self.prepare_execute(context)
    task._validate_compiler_configs(self.target('test_validate:one'))
    task._validate_compiler_configs(self.target('test_validate:two'))

  def test_scala(self):
    sources = [os.path.join(self.test_workdir, 'org/pantsbuild/example/Example.scala')]
    self._test_help('scala', ScalaLibrary, [GEN_ADAPT], sources)

  def test_compiler_args(self):
    sources = [os.path.join(self.test_workdir, 'org/pantsbuild/example/Example.scala')]
    self._test_help('scala', ScalaLibrary, [GEN_ADAPT], sources)

  def test_android(self):
    sources = [os.path.join(self.test_workdir, 'org/pantsbuild/android_example/Example.java')]
    self._test_help('android', JavaLibrary, [GEN_ADAPT], sources)

  def test_invalid_lang(self):
    with self.assertRaises(TargetDefinitionException):
      self._test_help('not-a-lang', JavaLibrary, [GEN_ADAPT], [])

  def test_empty_compiler_args(self):
    sources = [os.path.join(self.test_workdir, 'org/pantsbuild/example/Example.scala')]
    self._test_help('scala', ScalaLibrary, [], sources)

  def compiler_args_to_string(self, compiler_args):
    quoted = ["'{}'".format(x) for x in compiler_args]
    comma_separated = ', '.join(quoted)
    return '[{}]'.format(comma_separated)

  def _test_create_build_str(self, language, compiler_args):
    compiler_args_str = self.compiler_args_to_string(compiler_args)
    return dedent('''
      java_thrift_library(name='a',
        sources=['a.thrift'],
        dependencies=[],
        compiler='scrooge',
        language='{language}',
        compiler_args={compiler_args},
        strict_deps=True,
      )
    '''.format(language=language, compiler_args=compiler_args_str))

  def _test_help(self, language, library_type, compiler_args, sources):
    contents = dedent('''#@namespace android org.pantsbuild.android_example
      namespace java org.pantsbuild.example
      struct Example {
      1: optional i64 number
      }
    ''')

    self.create_file(relpath='test_smoke/a.thrift', contents=contents)
    build_string = self._test_create_build_str(language, compiler_args)
    self.add_to_build_file('test_smoke', build_string)

    target = self.target('test_smoke:a')
    context = self.context(target_roots=[target])
    task = self.prepare_execute(context)

    task.gen = MagicMock()
    task.gen.return_value = {'test_smoke/a.thrift': sources}

    saved_add_new_target = Context.add_new_target
    try:
      mock = MagicMock()
      Context.add_new_target = mock
      task.execute()

      self.assertEqual(1, mock.call_count)
      _, call_kwargs = mock.call_args
      self.assertEqual(call_kwargs['target_type'], library_type)
      self.assertEqual(call_kwargs['dependencies'], OrderedSet())
      self.assertEqual(call_kwargs['provides'], None)
      self.assertEqual(call_kwargs['derived_from'], target)
      self.assertEqual(call_kwargs['strict_deps'], True)

      sources = call_kwargs['sources']
      self.assertEqual(sources.files, ())

    finally:
      Context.add_new_target = saved_add_new_target

  def test_basic_deps(self):
    contents = dedent('''#@namespace android org.pantsbuild.android_example
      namespace java org.pantsbuild.example
      struct Example {
      1: optional i64 number
      }
    ''')
    self._test_dependencies_help(contents, False, False)

  def test_service_deps(self):
    contents = dedent('''#@namespace android org.pantsbuild.android_example
      namespace java org.pantsbuild.example
      service MultiplicationService
      {
        int multiply(1:int n1, 2:int n2),
      }''')
    self._test_dependencies_help(contents, True, False)

  def test_exception_deps(self):
    contents = dedent('''#@namespace android org.pantsbuild.android_example
      namespace java org.pantsbuild.example
      exception InvalidOperation {
        1: i32 what,
        2: string why
      }''')
    self._test_dependencies_help(contents, False, True)

  def _test_dependencies_help(self, contents, declares_service, declares_exception):
    source = 'test_smoke/a.thrift'
    self.create_file(relpath=source, contents=contents)
    self.assertEqual(ScroogeGen._declares_service(source), declares_service)
    self.assertEqual(ScroogeGen._declares_exception(source), declares_exception)
