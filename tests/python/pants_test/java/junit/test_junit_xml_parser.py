# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.java.junit.junit_xml_parser import Test as JUnitTest
# NB: The Test -> JUnitTest import re-name above is needed to work around conflicts with pytest test
# collection and a conflicting Test type in scope during that process.
from pants.java.junit.junit_xml_parser import ParseError, RegistryOfTests, parse_failed_targets
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants.util.xml_parser import XmlParser


class TestTest(unittest.TestCase):
  def setUp(self):
    self.class_test = JUnitTest('class')
    self.method_test = JUnitTest('class', 'method')

  def test_no_method_normalization(self):
    def test_normalization(variant):
      self.assertEqual(variant, self.class_test)
      self.assertIsNone(variant.methodname)

    test_normalization(JUnitTest('class', ''))
    test_normalization(JUnitTest('class', None))
    test_normalization(JUnitTest('class'))

  def test_enclosing(self):
    self.assertIs(self.class_test, self.class_test.enclosing())
    self.assertEqual(self.class_test, self.method_test.enclosing())

  def test_render_test_spec(self):
    self.assertEqual('class', self.class_test.render_test_spec())
    self.assertEqual('class#method', self.method_test.render_test_spec())


class TestTestRegistry(unittest.TestCase):
  def test_empty(self):
    self.assertTrue(RegistryOfTests({}).empty)
    self.assertTrue(RegistryOfTests(()).empty)
    self.assertTrue(RegistryOfTests([]).empty)

  def test_get_owning_target(self):
    registry = RegistryOfTests(((JUnitTest('class1'), 'Bob'),
                                (JUnitTest('class2'), 'Jane'),
                                (JUnitTest('class3', 'method1'), 'Heidi')))

    self.assertEqual('Bob', registry.get_owning_target(JUnitTest('class1')))
    self.assertEqual('Bob', registry.get_owning_target(JUnitTest('class1', 'method1')))

    self.assertEqual('Jane', registry.get_owning_target(JUnitTest('class2')))
    self.assertEqual('Jane', registry.get_owning_target(JUnitTest('class2', 'method1')))

    self.assertIsNone(registry.get_owning_target(JUnitTest('class3')))
    self.assertEqual('Heidi', registry.get_owning_target(JUnitTest('class3', 'method1')))

  def _assert_index(self, expected, actual):
    def sorted_values(index):
      # Eliminate unimportant ordering differences in the index values.
      return {key: sorted(values) for key, values in index.items()}

    self.assertEqual(sorted_values(expected), sorted_values(actual))

  def test_index_nominal(self):
    registry = RegistryOfTests({JUnitTest('class1'): (1, 'a'),
                                JUnitTest('class2'): (2, 'b'),
                                JUnitTest('class3', 'method1'): (1, 'a'),
                                JUnitTest('class3', 'method2'): (4, 'b')})

    actual_index = registry.index(lambda t: t[0], lambda t: t[1])
    expected_index = {(1, 'a'): (JUnitTest('class1'), JUnitTest('class3', 'method1')),
                      (2, 'b'): (JUnitTest('class2'),),
                      (4, 'b'): (JUnitTest('class3', 'method2'),)}
    self._assert_index(expected_index, actual_index)

  def test_index_empty(self):
    self._assert_index({}, RegistryOfTests({}).index())

  def test_index_no_indexers(self):
    registry = RegistryOfTests({JUnitTest('class1'): (1, 'a'),
                                JUnitTest('class2'): (2, 'b')})

    self._assert_index({(): (JUnitTest('class1'), JUnitTest('class2'))}, registry.index())


class TestParseFailedTargets(unittest.TestCase):
  @staticmethod
  def _raise_handler(e):
    raise e

  class CollectHandler(object):
    def __init__(self):
      self._errors = []

    def __call__(self, e):
      self._errors.append(e)

    @property
    def errors(self):
      return self._errors

  def test_parse_failed_targets_no_files(self):
    registry = RegistryOfTests({})
    with temporary_dir() as junit_xml_dir:
      failed_targets = parse_failed_targets(registry, junit_xml_dir, self._raise_handler)

      self.assertEqual({}, failed_targets)

  def test_parse_failed_targets_nominal(self):
    registry = RegistryOfTests({JUnitTest('org.pantsbuild.Failure'): 'Bob',
                                JUnitTest('org.pantsbuild.Error'): 'Jane',
                                JUnitTest('org.pantsbuild.AnotherError'): 'Bob'})

    with temporary_dir() as junit_xml_dir:
      with open(os.path.join(junit_xml_dir, 'TEST-a.xml'), 'w') as fp:
        fp.write("""
        <testsuite failures="1" errors="1">
          <testcase classname="org.pantsbuild.Green" name="testOK"/>
          <testcase classname="org.pantsbuild.Failure" name="testFailure">
            <failure/>
          </testcase>
          <testcase classname="org.pantsbuild.Error" name="testError">
            <error/>
          </testcase>
        </testsuite>
        """)
      with open(os.path.join(junit_xml_dir, 'TEST-b.xml'), 'w') as fp:
        fp.write("""
        <testsuite failures="0" errors="1">
          <testcase classname="org.pantsbuild.AnotherError" name="testAnotherError">
            <error/>
          </testcase>
        </testsuite>
        """)
      with open(os.path.join(junit_xml_dir, 'random.xml'), 'w') as fp:
        fp.write('<invalid></xml>')
      with safe_open(os.path.join(junit_xml_dir, 'subdir', 'TEST-c.xml'), 'w') as fp:
        fp.write('<invalid></xml>')

      failed_targets = parse_failed_targets(registry, junit_xml_dir, self._raise_handler)
      self.assertEqual({'Bob': {JUnitTest('org.pantsbuild.Failure', 'testFailure'),
                                JUnitTest('org.pantsbuild.AnotherError', 'testAnotherError')},
                        'Jane': {JUnitTest('org.pantsbuild.Error', 'testError')}},
                       failed_targets)

  def test_parse_failed_targets_error_raise(self):
    registry = RegistryOfTests({})
    with temporary_dir() as junit_xml_dir:
      junit_xml_file = os.path.join(junit_xml_dir, 'TEST-bad.xml')
      with open(junit_xml_file, 'w') as fp:
        fp.write('<invalid></xml>')
      with self.assertRaises(ParseError) as exc:
        parse_failed_targets(registry, junit_xml_dir, self._raise_handler)
      self.assertEqual(junit_xml_file, exc.exception.junit_xml_path)
      self.assertIsInstance(exc.exception.cause, XmlParser.XmlError)

  def test_parse_failed_targets_error_continue(self):
    registry = RegistryOfTests({})
    with temporary_dir() as junit_xml_dir:
      bad_file1 = os.path.join(junit_xml_dir, 'TEST-bad1.xml')
      with open(bad_file1, 'w') as fp:
        fp.write('<testsuite failures="nan" errors="0"/>')
      with open(os.path.join(junit_xml_dir, 'TEST-good.xml'), 'w') as fp:
        fp.write("""
        <testsuite failures="0" errors="1">
          <testcase classname="org.pantsbuild.Error" name="testError">
            <error/>
          </testcase>
        </testsuite>
        """)
      bad_file2 = os.path.join(junit_xml_dir, 'TEST-bad2.xml')
      with open(bad_file2, 'w') as fp:
        fp.write('<invalid></xml>')

      collect_handler = self.CollectHandler()
      failed_targets = parse_failed_targets(registry, junit_xml_dir, collect_handler)
      self.assertEqual(2, len(collect_handler.errors))
      self.assertEqual({bad_file1, bad_file2}, {e.junit_xml_path for e in collect_handler.errors})

      self.assertEqual({None: {JUnitTest('org.pantsbuild.Error', 'testError')}}, failed_targets)
