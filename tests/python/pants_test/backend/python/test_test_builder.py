# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import xml.dom.minidom as DOM
from textwrap import dedent

import coverage
from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.test_builder import PythonTestBuilder
from pants.base.build_file_aliases import BuildFileAliases
from pants.util.contextutil import environment_as, pushd
from pants_test.base_test import BaseTest


class PythonTestBuilderTestBase(BaseTest):
  def setUp(self):
    super(PythonTestBuilderTestBase, self).setUp()
    self.set_options_for_scope('', python_chroot_requirements_ttl=1000000000)

  def _cache_current_interpreter(self):
    cache = PythonInterpreterCache(self.config())

    # We only need to cache the current interpreter, avoid caching for every interpreter on the
    # PATH.
    current_interpreter = PythonInterpreter.get()
    for cached_interpreter in cache.setup(paths=[current_interpreter.binary]):
      if cached_interpreter == current_interpreter:
        return cached_interpreter
    raise RuntimeError('Could not find suitable interpreter to run tests.')

  def run_tests(self, targets, args=None, fast=True, debug=False):
    test_builder = PythonTestBuilder(
        self.context(),
        targets, args or [], fast=fast, debug=debug, interpreter=self._cache_current_interpreter())

    with pushd(self.build_root):
      return test_builder.run()


class PythonTestBuilderTestEmpty(PythonTestBuilderTestBase):
  def test_empty(self):
    self.assertEqual(0, self.run_tests(targets=[]))


class PythonTestBuilderTest(PythonTestBuilderTestBase):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
        targets={
            'python_library': PythonLibrary,
            'python_tests': PythonTests
        })

  def setUp(self):
    super(PythonTestBuilderTest, self).setUp()

    self.create_file(
        'lib/core.py',
        dedent('''
          def one():  # line 1
            return 1  # line 2
                      # line 3
                      # line 4
          def two():  # line 5
            return 2  # line 6
        ''').strip())
    self.add_to_build_file(
        'lib',
        dedent('''
          python_library(
            name='core',
            sources=[
              'core.py'
            ]
          )
        '''))

    self.create_file(
        'tests/test_core_green.py',
        dedent('''
          import unittest2 as unittest

          import core

          class CoreGreenTest(unittest.TestCase):
            def test_one(self):
              self.assertEqual(1, core.one())
        '''))
    self.create_file(
        'tests/test_core_red.py',
        dedent('''
          import core

          def test_two():
            assert 1 == core.two()
        '''))
    self.add_to_build_file(
        'tests',
        dedent('''
          python_tests(
            name='green',
            sources=[
              'test_core_green.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='red',
            sources=[
              'test_core_red.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )

          python_tests(
            name='all',
            sources=[
              'test_core_green.py',
              'test_core_red.py'
            ],
            dependencies=[
              'lib:core'
            ]
          )

          python_tests(
            name='all-with-coverage',
            sources=[
              'test_core_green.py',
              'test_core_red.py'
            ],
            dependencies=[
              'lib:core'
            ],
            coverage=[
              'core'
            ]
          )
        '''))
    self.green = self.target('tests:green')
    self.red = self.target('tests:red')
    self.all = self.target('tests:all')
    self.all_with_coverage = self.target('tests:all-with-coverage')

  def test_green(self):
    self.assertEqual(0, self.run_tests(targets=[self.green]))

  def test_red(self):
    self.assertEqual(1, self.run_tests(targets=[self.red]))

  def test_mixed(self):
    self.assertEqual(1, self.run_tests(targets=[self.green, self.red]))

  def test_junit_xml(self):
    # We expect xml of the following form:
    # <testsuite errors=[Ne] failures=[Nf] skips=[Ns] tests=[Nt] ...>
    #   <testcase classname="..." name="..." .../>
    #   <testcase classname="..." name="..." ...>
    #     <failure ...>...</failure>
    #   </testcase>
    # </testsuite>

    report_basedir = os.path.join(self.build_root, 'dist', 'junit')
    with environment_as(JUNIT_XML_BASE=report_basedir):
      self.assertEqual(1, self.run_tests(targets=[self.red, self.green]))

      files = glob.glob(os.path.join(report_basedir, '*.xml'))
      self.assertEqual(1, len(files))
      junit_xml = files[0]
      with open(junit_xml) as fp:
        print(fp.read())

      root = DOM.parse(junit_xml).documentElement
      self.assertEqual(2, len(root.childNodes))
      self.assertEqual(2, int(root.getAttribute('tests')))
      self.assertEqual(1, int(root.getAttribute('failures')))
      self.assertEqual(0, int(root.getAttribute('errors')))
      self.assertEqual(0, int(root.getAttribute('skips')))

      children_by_test_name = dict((elem.getAttribute('name'), elem) for elem in root.childNodes)
      self.assertEqual(0, len(children_by_test_name['test_one'].childNodes))
      self.assertEqual(1, len(children_by_test_name['test_two'].childNodes))
      self.assertEqual('failure', children_by_test_name['test_two'].firstChild.nodeName)

  def coverage_data_file(self):
    return os.path.join(self.build_root, '.coverage')

  def load_coverage_data(self, path):
    data_file = self.coverage_data_file()
    self.assertTrue(os.path.isfile(data_file))
    coverage_data = coverage.coverage(data_file=data_file)
    coverage_data.load()
    _, all_statements, not_run_statements, _ = coverage_data.analysis(path)
    return all_statements, not_run_statements

  def test_coverage_simple(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    covered_file = os.path.join(self.build_root, 'lib', 'core.py')
    with environment_as(PANTS_PY_COVERAGE='1'):
      self.assertEqual(0, self.run_tests(targets=[self.green]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([6], not_run_statements)

      self.assertEqual(1, self.run_tests(targets=[self.red]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([2], not_run_statements)

      self.assertEqual(1, self.run_tests(targets=[self.green, self.red]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

      # The all target has no coverage attribute and the code under test does not follow the
      # auto-discover pattern so we should get no coverage.
      self.assertEqual(1, self.run_tests(targets=[self.all]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([1, 2, 5, 6], not_run_statements)

      self.assertEqual(1, self.run_tests(targets=[self.all_with_coverage]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

  def test_coverage_modules(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    covered_file = os.path.join(self.build_root, 'lib', 'core.py')
    with environment_as(PANTS_PY_COVERAGE='modules:does_not_exist,nor_does_this'):
      # modules: should trump .coverage
      self.assertEqual(1, self.run_tests(targets=[self.green, self.red]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([1, 2, 5, 6], not_run_statements)

    with environment_as(PANTS_PY_COVERAGE='modules:core'):
      self.assertEqual(1, self.run_tests(targets=[self.all]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)

  def test_coverage_paths(self):
    self.assertFalse(os.path.isfile(self.coverage_data_file()))
    covered_file = os.path.join(self.build_root, 'lib', 'core.py')
    with environment_as(PANTS_PY_COVERAGE='paths:does_not_exist/,nor_does_this/'):
      # paths: should trump .coverage
      self.assertEqual(1, self.run_tests(targets=[self.green, self.red]))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([1, 2, 5, 6], not_run_statements)

    with environment_as(PANTS_PY_COVERAGE='paths:core.py'):
      self.assertEqual(1, self.run_tests(targets=[self.all], debug=True))
      all_statements, not_run_statements = self.load_coverage_data(covered_file)
      self.assertEqual([1, 2, 5, 6], all_statements)
      self.assertEqual([], not_run_statements)
