# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from textwrap import dedent

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.python_eval import PythonEval
from pants.base.address import SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.test_base import TaskTest


class PythonEvalTest(TaskTest):
  @classmethod
  def task_type(cls):
    return PythonEval

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'python_library': PythonLibrary,
                                            'python_binary': PythonBinary})

  def create_python_library(self, relpath, name, source, contents, dependencies=()):
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    python_library(
      name='{name}',
      sources=['__init__.py', '{source}'],
      dependencies=[
        {dependencies}
      ]
    )
    """).format(name=name, source=source, dependencies=','.join(map(repr, dependencies))))

    self.create_file(relpath=os.path.join(relpath, '__init__.py'))
    self.create_file(relpath=os.path.join(relpath, source), contents=contents)
    return self.target(SyntheticAddress(relpath, name).spec)

  def create_python_binary(self, relpath, name, entry_point, dependencies=()):
    self.create_file(relpath=self.build_path(relpath), contents=dedent("""
    python_binary(
      name='{name}',
      entry_point='{entry_point}',
      dependencies=[
        {dependencies}
      ]
    )
    """).format(name=name, entry_point=entry_point, dependencies=','.join(map(repr, dependencies))))

    return self.target(SyntheticAddress(relpath, name).spec)

  def setUp(self):
    super(PythonEvalTest, self).setUp()

    # Re-use the main pants python cache to speed up interpreter selection and artifact resolution.
    # TODO(John Sirois): Lift this up to TaskTest or else to a PythonTaskTest base class so more
    # tests can pickup the speed improvement.
    safe_mkdir(os.path.join(self.build_root, '.pants.d'))
    shutil.copytree(os.path.join(self.real_build_root, '.pants.d', 'python'),
                    os.path.join(self.build_root, '.pants.d', 'python'),
                    symlinks=True)

    SourceRoot.register('src', PythonBinary, PythonLibrary)

    self.a = self.create_python_library('src/foo', 'a', 'a.py', dedent("""
    import inspect


    def compile_time_check_decorator(cls):
      if not inspect.isclass(cls):
        raise TypeError('This decorator can only be applied to classes, given {}'.format(cls))
      return cls
    """))

    self.b = self.create_python_library('src/bar', 'b', 'b.py', dedent("""
    from foo.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BarB(object):
      pass
    """))

    self.c = self.create_python_library('src/baz', 'c', 'c.py', dedent("""
    from foo.a import compile_time_check_decorator


    @compile_time_check_decorator
    def baz_c():
      pass
    """), dependencies=['//src/foo:a'])

    def fix_c_source():
      self.create_file('src/baz/c.py', contents=dedent("""
      from foo.a import compile_time_check_decorator

      # Change from decorated function baz_c to decorated class BazC.
      @compile_time_check_decorator
      class BazC(object):
        pass
      """))
    self.fix_c_source = fix_c_source

    self.d = self.create_python_library('src/egg', 'd', 'd.py', dedent("""
    from foo.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BazD(object):
      pass
    """), dependencies=['//src/foo:a'])

    self.e = self.create_python_binary('src/spam', 'e', 'foo.a', dependencies=['//src/foo:a'])
    self.f = self.create_python_binary('src/tang', 'f', 'foo.a:compile_time_check_decorator',
                                       dependencies=['//src/foo:a'])
    self.g = self.create_python_binary('src/elderberries', 'g', 'foo.a:does_not_exist',
                                       dependencies=['//src/foo:a'])
    self.h = self.create_python_binary('src/poprockz', 'h', 'foo.a')

  def tearDown(self):
    SourceRoot.reset()

  def test_noop(self):
    python_eval = self.prepare_task(targets=[],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile(self):
    python_eval = self.prepare_task(targets=[self.a],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([self.a], compiled)

  def test_compile_incremental(self):
    python_eval = self.prepare_task(targets=[self.a],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([self.a], compiled)

    python_eval = self.prepare_task(targets=[self.a],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile_closure(self):
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.d],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual({self.d, self.a}, set(compiled))

  def test_compile_fail_closure(self):
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.c],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([self.a], e.exception.compiled)
    self.assertEqual([self.c], e.exception.failed)

  def test_compile_incremental_progress(self):
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.c],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([self.a], e.exception.compiled)
    self.assertEqual([self.c], e.exception.failed)

    self.fix_c_source()
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.c],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    compiled = python_eval.execute()
    self.assertEqual([self.c], compiled)

  def test_compile_fail_missing_build_dep(self):
    python_eval = self.prepare_task(targets=[self.b],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(python_eval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.b], e.exception.failed)

  def test_compile_fail_compile_time_check_decorator(self):
    python_eval = self.prepare_task(targets=[self.c],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.c], e.exception.failed)

  def test_compile_failslow(self):
    python_eval = self.prepare_task(args=['--test-fail-slow'],
                                    targets=[self.a, self.c, self.d],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual({self.a, self.d}, set(e.exception.compiled))
    self.assertEqual([self.c], e.exception.failed)

  def test_entry_point_module(self):
    python_eval = self.prepare_task(targets=[self.e],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    compiled = python_eval.execute()
    self.assertEqual([self.e], compiled)

  def test_entry_point_function(self):
    python_eval = self.prepare_task(targets=[self.f],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    compiled = python_eval.execute()
    self.assertEqual([self.f], compiled)

  def test_entry_point_does_not_exist(self):
    python_eval = self.prepare_task(targets=[self.g],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.g], e.exception.failed)

  def test_entry_point_missing_build_dep(self):
    python_eval = self.prepare_task(targets=[self.h],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.h], e.exception.failed)