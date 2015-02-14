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
from pants.util.dirutil import safe_mkdir
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

    self.foo_library = self.create_python_library('src/foo', 'a', 'a.py', dedent("""
    import inspect


    def compile_time_check_decorator(cls):
      if not inspect.isclass(cls):
        raise TypeError('This decorator can only be applied to classes, given {}'.format(cls))
      return cls
    """))

    self.bar_library = self.create_python_library('src/bar', 'b', 'b.py', dedent("""
    from foo.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BarB(object):
      pass
    """))

    self.baz_library = self.create_python_library('src/baz', 'c', 'c.py', dedent("""
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

    self.egg_library = self.create_python_library('src/egg', 'd', 'd.py', dedent("""
    from foo.a import compile_time_check_decorator


    @compile_time_check_decorator
    class BazD(object):
      pass
    """), dependencies=['//src/foo:a'])

    self.spam_binary = self.create_python_binary('src/spam', 'e', 'foo.a',
                                                 dependencies=['//src/foo:a'])
    self.tang_binary = self.create_python_binary('src/tang', 'f',
                                                 'foo.a:compile_time_check_decorator',
                                                 dependencies=['//src/foo:a'])
    self.elerberries_binary = self.create_python_binary('src/elderberries', 'g',
                                                        'foo.a:does_not_exist',
                                                        dependencies=['//src/foo:a'])
    self.poprockz_binary = self.create_python_binary('src/poprockz', 'h', 'foo.a')

  def tearDown(self):
    SourceRoot.reset()

  def test_noop(self):
    python_eval = self.prepare_task(targets=[],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile(self):
    python_eval = self.prepare_task(targets=[self.foo_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([self.foo_library], compiled)

  def test_compile_incremental(self):
    python_eval = self.prepare_task(targets=[self.foo_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([self.foo_library], compiled)

    python_eval = self.prepare_task(targets=[self.foo_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual([], compiled)

  def test_compile_closure(self):
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.egg_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)
    compiled = python_eval.execute()
    self.assertEqual({self.egg_library, self.foo_library}, set(compiled))

  def test_compile_fail_closure(self):
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.baz_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([self.foo_library], e.exception.compiled)
    self.assertEqual([self.baz_library], e.exception.failed)

  def test_compile_incremental_progress(self):
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.baz_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([self.foo_library], e.exception.compiled)
    self.assertEqual([self.baz_library], e.exception.failed)

    self.fix_c_source()
    python_eval = self.prepare_task(args=['--test-closure'],
                                    targets=[self.baz_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    compiled = python_eval.execute()
    self.assertEqual([self.baz_library], compiled)

  def test_compile_fail_missing_build_dep(self):
    python_eval = self.prepare_task(targets=[self.bar_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(python_eval.Error) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.bar_library], e.exception.failed)

  def test_compile_fail_compile_time_check_decorator(self):
    python_eval = self.prepare_task(targets=[self.baz_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.baz_library], e.exception.failed)

  def test_compile_failslow(self):
    python_eval = self.prepare_task(args=['--test-fail-slow'],
                                    targets=[self.foo_library, self.baz_library, self.egg_library],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual({self.foo_library, self.egg_library}, set(e.exception.compiled))
    self.assertEqual([self.baz_library], e.exception.failed)

  def test_entry_point_module(self):
    python_eval = self.prepare_task(targets=[self.spam_binary],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    compiled = python_eval.execute()
    self.assertEqual([self.spam_binary], compiled)

  def test_entry_point_function(self):
    python_eval = self.prepare_task(targets=[self.tang_binary],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    compiled = python_eval.execute()
    self.assertEqual([self.tang_binary], compiled)

  def test_entry_point_does_not_exist(self):
    python_eval = self.prepare_task(targets=[self.elerberries_binary],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.elerberries_binary], e.exception.failed)

  def test_entry_point_missing_build_dep(self):
    python_eval = self.prepare_task(targets=[self.poprockz_binary],
                                    build_graph=self.build_graph,
                                    build_file_parser=self.build_file_parser)

    with self.assertRaises(TaskError) as e:
      python_eval.execute()
    self.assertEqual([], e.exception.compiled)
    self.assertEqual([self.poprockz_binary], e.exception.failed)
