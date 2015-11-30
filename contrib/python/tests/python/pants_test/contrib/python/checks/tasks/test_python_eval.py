# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase

from pants.contrib.python.checks.tasks.python_eval import PythonEval


class PythonEvalTest(PythonTaskTestBase):

  @classmethod
  def task_type(cls):
    return PythonEval

  def setUp(self):
    super(PythonEvalTest, self).setUp()
    self._create_graph(broken_b_library=True)

  def _create_graph(self, broken_b_library):
    self.reset_build_graph()

    self.a_library = self.create_python_library('src/python/a', 'a', {'a.py': dedent("""
    import inspect


    def compile_time_check_decorator(cls):
      if not inspect.isclass(cls):
        raise TypeError('This decorator can only be applied to classes, given {}'.format(cls))
      return cls
    """)})

    self.b_library = self.create_python_library('src/python/b', 'b', {'b.py': dedent("""
    from a.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BarB(object):
      pass
    """)})

    # TODO: Presumably this was supposed to be c_library, not override b_library. Unravel and fix.
    self.b_library = self.create_python_library('src/python/c', 'c', {'c.py': dedent("""
    from a.a import compile_time_check_decorator


    @compile_time_check_decorator
    {}:
      pass
    """.format('def baz_c()' if broken_b_library else 'class BazC(object)')
    )}, dependencies=['//src/python/a'])

    self.d_library = self.create_python_library('src/python/d', 'd', { 'd.py': dedent("""
    from a.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BazD(object):
      pass
    """)}, dependencies=['//src/python/a'])

    self.e_binary = self.create_python_binary('src/python/e', 'e', 'a.a',
                                              dependencies=['//src/python/a'])
    self.f_binary = self.create_python_binary('src/python/f', 'f',
                                              'a.a:compile_time_check_decorator',
                                              dependencies=['//src/python/a'])
    self.g_binary = self.create_python_binary('src/python/g', 'g', 'a.a:does_not_exist',
                                              dependencies=['//src/python/a'])
    self.h_binary = self.create_python_binary('src/python/h', 'h', 'a.a')

  def _create_task(self, target_roots, options=None):
    if options:
      self.set_options(**options)
    return self.create_task(self.context(target_roots=target_roots))

  def test_noop(self):
    python_eval = self._create_task(target_roots=[])
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile(self):
    python_eval = self._create_task(target_roots=[self.a_library])
    compiled = python_eval.execute()
    self.assertEqual([self.a_library], compiled)

  def test_skip(self):
    self.set_options(skip=True)
    python_eval = self._create_task(target_roots=[self.a_library])
    compiled = python_eval.execute()
    self.assertIsNone(compiled)

  def test_compile_incremental(self):
    python_eval = self._create_task(target_roots=[self.a_library])
    compiled = python_eval.execute()
    self.assertEqual([self.a_library], compiled)

    python_eval = self._create_task(target_roots=[self.a_library])
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile_closure(self):
    python_eval = self._create_task(target_roots=[self.d_library], options={'closure': True})
    compiled = python_eval.execute()
    self.assertEqual({self.d_library, self.a_library}, set(compiled))

  def test_compile_fail_closure(self):
    python_eval = self._create_task(target_roots=[self.b_library], options={'closure': True})

    with self.assertRaises(PythonEval.Error) as e:
      python_eval.execute()
    self.assertEqual([self.a_library], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

  def test_compile_incremental_progress(self):
    python_eval = self._create_task(target_roots=[self.b_library], options={'closure': True})

    with self.assertRaises(PythonEval.Error) as e:
      python_eval.execute()
    self.assertEqual([self.a_library], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

    self._create_graph(broken_b_library=False)
    python_eval = self._create_task(target_roots=[self.b_library], options={'closure': True})

    compiled = python_eval.execute()
    self.assertEqual([self.b_library], compiled)

  def test_compile_fail_missing_build_dep(self):
    python_eval = self._create_task(target_roots=[self.b_library])

    with self.assertRaises(python_eval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

  def test_compile_fail_compile_time_check_decorator(self):
    python_eval = self._create_task(target_roots=[self.b_library])

    with self.assertRaises(PythonEval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.b_library], e.exception.failed)

  def test_compile_failslow(self):
    python_eval = self._create_task(target_roots=[self.a_library, self.b_library, self.d_library],
                                    options={'fail_slow': True})

    with self.assertRaises(PythonEval.Error) as e:
      python_eval.execute()
    self.assertEqual({self.a_library, self.d_library}, set(e.exception.compiled))
    self.assertEqual([self.b_library], e.exception.failed)

  def test_entry_point_module(self):
    python_eval = self._create_task(target_roots=[self.e_binary])

    compiled = python_eval.execute()
    self.assertEqual([self.e_binary], compiled)

  def test_entry_point_function(self):
    python_eval = self._create_task(target_roots=[self.f_binary])

    compiled = python_eval.execute()
    self.assertEqual([self.f_binary], compiled)

  def test_entry_point_does_not_exist(self):
    python_eval = self._create_task(target_roots=[self.g_binary])

    with self.assertRaises(PythonEval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.g_binary], e.exception.failed)

  def test_entry_point_missing_build_dep(self):
    python_eval = self._create_task(target_roots=[self.h_binary])

    with self.assertRaises(PythonEval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.h_binary], e.exception.failed)
