# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.graph_info.tasks.graph_conditions import Conditions
from pants.backend.graph_info.tasks.graph_queries import GraphQueries
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants_test.tasks.task_test_base import TaskTestBase


class GraphQueriesTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GraphQueries

  def assert_type_name(self, expected_name, obj):
    self.assertEquals(expected_name, type(obj).__name__)

  def assert_condition(self, expected_type, data):
    condition = Conditions(data)
    self.assert_type_name(expected_type, condition)
    return condition

  def run_query(self, expected_targets, context, query):
    predicate = Conditions(query)
    received_targets = {t for t in context.targets() if predicate(context, t)}
    self.assertEquals(set(expected_targets), received_targets)

  def _lib_tests_context(self):
    common = self.make_target('common:common', target_type=JavaLibrary)
    library = self.make_target('foobar:lib', target_type=JavaLibrary, dependencies=[common])
    tests = self.make_target('raboof:test', target_type=JavaTests, dependencies=[library])
    context = self.context(target_roots=[library, tests])
    return common, library, tests, context

  def test_parse_simple_conditions(self):
    self.assert_condition('IsType', {'type': 'java_library'})
    self.assert_condition('HasSources', {'sources': ''})
    self.assert_condition('NameMatches', {'name': ''})
    self.assert_condition('SpecMatches', {'spec': ''})

  def test_parse_compound_conditions(self):
    had_dependency_dict = {'dependency': {'target': {'name': 'lib'}}}
    has_dependee_dict = {'dependee': {'target': {'type': 'java_tests'}}}

    has_dependency = self.assert_condition('HasDependency', had_dependency_dict)
    has_dependee = self.assert_condition('HasDependee', has_dependee_dict)

    meta_all = self.assert_condition('All', {'all': [had_dependency_dict, has_dependee_dict]})
    meta_any = self.assert_condition('Any', {'any': [had_dependency_dict, has_dependee_dict]})
    meta_not = self.assert_condition('Not', {'not': had_dependency_dict})

    self.assert_type_name('NameMatches', has_dependency[0])
    self.assert_type_name('IsType', has_dependee[0])

    for meta in meta_all, meta_any:
      self.assert_type_name('HasDependency', meta[0])
      self.assert_type_name('HasDependee', meta[1])
      self.assert_type_name('NameMatches', meta[0][0])
      self.assert_type_name('IsType', meta[1][0])

    self.assert_type_name('HasDependency', meta_not[0])

  def test_name_matches(self):
    apple = self.make_target('testing-file:apple')
    orange = self.make_target('testing-file:orange')
    context = self.context(target_roots=[apple, orange])

    self.run_query(
      expected_targets=[apple, orange],
      context=context,
      query={'name': '.*?a.*'},
    )
    self.run_query(
      expected_targets=[orange],
      context=context,
      query={'name': '.*?ng.*'},
    )

  def test_spec_matches(self):
    apple = self.make_target('testing-file:apple')
    orange = self.make_target('testing-path:orange')
    context = self.context(target_roots=[apple, orange])

    self.run_query(
      expected_targets=[apple, orange],
      context=context,
      query={'spec': '.*?a.*'},
    )
    self.run_query(
      expected_targets=[apple, orange],
      context=context,
      query={'spec': '.*?ng.*'},
    )
    self.run_query(
      expected_targets=[apple],
      context=context,
      query={'spec': '.*?file:'},
    )
    self.run_query(
      expected_targets=[orange],
      context=context,
      query={'spec': '.*?path:'},
    )

  def test_not(self):
    common, library, tests, context = self._lib_tests_context()

    self.run_query(
      expected_targets=[tests, common],
      context=context,
      query={'not': {'name': 'lib'}},
    )
    self.run_query(
      expected_targets=[library, common],
      context=context,
      query={'not': {'name': 'test'}},
    )

  def test_has_dependency(self):
    common, library, tests, context = self._lib_tests_context()

    self.run_query(
      expected_targets=[library, tests],
      context=context,
      query={'dependency': {'target': {'name': 'common'}}},
    )
    self.run_query(
      expected_targets=[library],
      context=context,
      query={'dependency': {'target': {'name': 'common'}, 'transitive': False}},
    )

  def test_has_dependee(self):
    common, library, tests, context = self._lib_tests_context()

    self.run_query(
      expected_targets=[common, library],
      context=context,
      query={'dependee': {'target': {'name': 'test'}}},
    )
    self.run_query(
      expected_targets=[library],
      context=context,
      query={'dependee': {'target': {'name': 'test'}, 'transitive': False}},
    )

  def test_all(self):
    common, library, tests, context = self._lib_tests_context()

    self.run_query(
      expected_targets=[library],
      context=context,
      query={'all': [
        {'dependency': {'target': {'name': 'common'}}},
        {'dependee': {'target': {'name': 'test'}}},
      ]},
    )

  def test_any(self):
    common, library, tests, context = self._lib_tests_context()

    self.run_query(
      expected_targets=[common, library, tests],
      context=context,
      query={'any': [
        {'dependency': {'target': {'name': 'common'}}},
        {'dependee': {'target': {'name': 'test'}}},
      ]},
    )
    self.run_query(
      expected_targets=[common, library],
      context=context,
      query={'any': [
        {'dependency': {'transitive': False, 'target': {'name': 'common'}}},
        {'dependee': {'target': {'name': 'test'}}},
      ]},
    )
