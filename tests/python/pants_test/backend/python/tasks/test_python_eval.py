# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.python_eval import PythonEval
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants_test.backend.python.tasks.python_task_test import PythonTaskTest


class PythonEvalTest(PythonTaskTest):
  @classmethod
  def task_type(cls):
    return PythonEval

  def setUp(self):
    super(PythonEvalTest, self).setUp()

    SourceRoot.register('src', PythonBinary, PythonLibrary)

    self.a_library = self.create_python_library('src/a', 'a', 'a.py', dedent("""
    import inspect


    def compile_time_check_decorator(cls):
      if not inspect.isclass(cls):
        raise TypeError('This decorator can only be applied to classes, given {}'.format(cls))
      return cls
    """))

    self.b_library = self.create_python_library('src/b', 'b', 'b.py', dedent("""
    from a.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BarB(object):
      pass
    """))

    self.b_library = self.create_python_library('src/c', 'c', 'c.py', dedent("""
    from a.a import compile_time_check_decorator


    @compile_time_check_decorator
    def baz_c():
      pass
    """), dependencies=['//src/a'])

    def fix_c_source():
      self.create_file('src/c/c.py', contents=dedent("""
      from a.a import compile_time_check_decorator

      # Change from decorated function baz_c to decorated class BazC.
      @compile_time_check_decorator
      class BazC(object):
        pass
      """))
    self.fix_c_source = fix_c_source

    self.d_library = self.create_python_library('src/d', 'd', 'd.py', dedent("""
    from a.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BazD(object):
      pass
    """), dependencies=['//src/a'])

    self.e_binary = self.create_python_binary('src/e', 'e', 'a.a', dependencies=['//src/a'])
    self.f_binary = self.create_python_binary('src/f', 'f', 'a.a:compile_time_check_decorator',
                                              dependencies=['//src/a'])
    self.g_binary = self.create_python_binary('src/g', 'g', 'a.a:does_not_exist',
                                              dependencies=['//src/a'])
    self.h_binary = self.create_python_binary('src/h', 'h', 'a.a')

  def tearDown(self):
    super(PythonEvalTest, self).tearDown()
    SourceRoot.reset()

  def prepare_task(self, *args, **kwargs):
    kwargs.update(build_graph=self.build_graph, build_file_parser=self.build_file_parser)
    return super(PythonEvalTest, self).prepare_task(*args, **kwargs)

  def test_noop(self):
    python_eval = self.prepare_task(targets=[])
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile(self):
    python_eval = self.prepare_task(targets=[self.a_library])
    compiled = python_eval.execute()
    self.assertEqual([self.a_library], compiled)

  def test_compile_incremental(self):
    python_eval = self.prepare_task(targets=[self.a_library])
    compiled = python_eval.execute()
    self.assertEqual([self.a_library], compiled)

    python_eval = self.prepare_task(targets=[self.a_library])
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile_closure(self):
    python_eval = self.prepare_task(args=['--test-closure'], targets=[self.d_library])
    compiled = python_eval.execute()
    self.assertEqual({self.d_library, self.a_library}, set(compiled))

  def test_compile_fail_closure(self):
    python_eval = self.prepare_task(args=['--test-closure'], targets=[self.b_library])

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([self.a_library], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

  def test_compile_incremental_progress(self):
    python_eval = self.prepare_task(args=['--test-closure'], targets=[self.b_library])

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([self.a_library], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

    self.fix_c_source()
    python_eval = self.prepare_task(args=['--test-closure'], targets=[self.b_library])

    compiled = python_eval.execute()
    self.assertEqual([self.b_library], compiled)

  def test_compile_fail_missing_build_dep(self):
    python_eval = self.prepare_task(targets=[self.b_library])

    with self.assertRaises(python_eval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

  def test_compile_fail_compile_time_check_decorator(self):
    python_eval = self.prepare_task(targets=[self.b_library])

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

  def test_compile_failslow(self):
    python_eval = self.prepare_task(args=['--test-fail-slow'],
                                    targets=[self.a_library, self.b_library, self.d_library])

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual({self.a_library, self.d_library}, set(e.exception.compiled))
    self.assertEqual([self.b_library], e.exception.failed)

  def test_entry_point_module(self):
    python_eval = self.prepare_task(targets=[self.e_binary])

    compiled = python_eval.execute()
    self.assertEqual([self.e_binary], compiled)

  def test_entry_point_function(self):
    python_eval = self.prepare_task(targets=[self.f_binary])

    compiled = python_eval.execute()
    self.assertEqual([self.f_binary], compiled)

  def test_entry_point_does_not_exist(self):
    python_eval = self.prepare_task(targets=[self.g_binary])

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.g_binary], e.exception.failed)

  def test_entry_point_missing_build_dep(self):
    python_eval = self.prepare_task(targets=[self.h_binary])

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.h_binary], e.exception.failed)
