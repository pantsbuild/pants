# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from contextlib import contextmanager

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GraphQueriesIntegrationTest(PantsRunIntegrationTest):
  """Integration tests for ./pants graph-queries."""

  def _spec_path(self, src_or_tests, name=''):
    return 'testprojects/{src}/java/org/pantsbuild/testproject/querysubjects{suffix}'.format(
      src=src_or_tests,
      suffix=name,
    )

  def test_query_subjects_setup(self):
    # Sanity check to make sure the test project works.
    self.assert_success(self.run_pants(['test', self._spec_path('src', '::'),
                                        self._spec_path('tests', '::')]))

  @contextmanager
  def query_file(self, json_dict):
    with temporary_dir() as directory:
      json_file = os.path.join(directory, 'query.json')
      with open(json_file, 'w') as f:
        f.write(json.dumps(json_dict))
      yield json_file

  def run_graph_queries(self, query, args=()):
    with self.query_file(query) as path:
      command = ['graph-query', '--query-file={}'.format(path)]
      command.extend(args)
      command.append(self._spec_path('src', '::'))
      command.append(self._spec_path('tests', '::'))
      return self.run_pants(command)

  def assert_query_returns(self, expected_targets, query, args=()):
    # First just check to make sure the yaml formatting works.
    result = self.run_graph_queries(query, ['--format=yaml'] + list(args))
    self.assert_success(result)
    # Now do it with Json so we can read the results easily.
    result = self.run_graph_queries(query, ['--format=json'] + list(args))
    self.assert_success(result)
    try:
      json_result = json.loads(result.stdout_data)
    except ValueError:
      raise ValueError('Failed to return valid json! Got: \n----\n{}\n----\n'.format(result))
    self.assertEquals(set(expected_targets), set(json_result))

  def test_find_both_of_my_java_files(self):
    self.assert_query_returns(
      expected_targets=[
        self._spec_path('src', ':my-java-file'),
        self._spec_path('tests', ':my-java-file'),
      ],
      query={
        'name': 'my-java-file',
      },
    )

  def test_find_java_libraries(self):
    self.assert_query_returns(
      expected_targets=[
        self._spec_path('src', ':my-java-file'),
        self._spec_path('src', ':another-file'),
        self._spec_path('src', ':untested-file'),
      ],
      query={
        'type': 'java_library',
      },
    )

  def test_find_java_tests(self):
    self.assert_query_returns(
      expected_targets=[
        self._spec_path('tests', ':my-java-file'),
        self._spec_path('tests', ':another-file'),
      ],
      query={
        'type': 'java_tests',
      },
    )

  def test_find_java_libraries_with_tests(self):
    self.assert_query_returns(
      expected_targets=[
        self._spec_path('src', ':my-java-file'),
        self._spec_path('src', ':another-file'),
      ],
      query={
        'type': 'java_library',
        'dependee': {'target': {'type': 'java_tests'}},
      },
    )

  def test_find_java_libraries_without_tests(self):
    self.assert_query_returns(
      expected_targets=[
        self._spec_path('src', ':untested-file'),
      ],
      query={
        'type': 'java_library',
        'not': {'dependee': {'target': {'type': 'java_tests'}}},
      },
    )

  def test_find_java_libraries_not_dependent_on_my_java_file(self):
    conditions = [
      {
        'not': {'dependency': {'target': {'name': 'my-java-file'}, 'transitive': False}},
      },
      # NB: It's kind of silly to excluding all non-java_library types instead of just specifying
      # that it should be a java_library, but this helps demonstrate the syntax for using multiple
      # "not" conditions in the same query.
      {
        'not': {'type': 'java_tests'},
      },
      {
        'not': {'type': 'jar_library'},
      },
      {
        'not': {'type': 'target'},
      }
    ]
    # Giving a list instead of a dict to --query should implicitly create an "all" condition.
    implicit_all_query = conditions
    explicit_all_query = { 'all': conditions }

    for query in implicit_all_query, explicit_all_query:
      self.assert_query_returns(
        expected_targets=[
          self._spec_path('src', ':my-java-file'),
          self._spec_path('src', ':untested-file'),
        ],
        query=query,
      )

  def test_fail_when_java_libraries_do_not_have_tests(self):
    result = self.run_graph_queries(
      query={
        'type': 'java_library',
        'not': {'dependee': {'target': {'type': 'java_tests'}}},
      },
      args=['--fail-if-not-empty', '--format=yaml'],
    )
    self.assert_failure(result)
    self.assertIn(self._spec_path('src', ':untested-file'), result.stdout_data)

  def test_fail_when_targets_do_not_have_tests(self):
    result = self.run_graph_queries(
      query=[
        {'not': {'type': 'java_tests'}},
        {'not': {'dependee': {'target': {'type': 'java_tests'}}}},
      ],
      args=['--fail-if-not-empty', '--format=yaml'],
    )
    self.assert_failure(result)
    self.assertIn(self._spec_path('src', ':untested-file'), result.stdout_data)
    self.assertIn(self._spec_path('src', ':untested-target'), result.stdout_data)

  def test_fail_fast_when_targets_do_not_have_tests(self):
    result = self.run_graph_queries(
      query=[
        {'not': {'type': 'java_tests'}},
        {'not': {'dependee': {'target': {'type': 'java_tests'}}}},
      ],
      args=['--fail-fast-if-not-empty', '--format=yaml'],
    )
    self.assert_failure(result)
    self.assertIn(self._spec_path('src', ':untested-file'), result.stdout_data)
    # We shouldn't get here because the fail-fast will trigger on the above target.
    self.assertNotIn(self._spec_path('src', ':untested-target'), result, 'We failed, but not fast.')

  def test_fail_if_no_binaries_are_present(self):
    result = self.run_graph_queries(
      query={'type': 'jvm_binary'},
      args=['--fail-if-empty', '--format=yaml'],
    )
    self.assert_failure(result)
    self.assertIn('Query found no targets, when it was supposed to find some.', result.stdout_data)
