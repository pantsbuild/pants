# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os

from pants.backend.graph_info.tasks.graph_conditions import Conditions
from pants.base.exceptions import TaskError
from pants.task.console_task import ConsoleTask


class GraphQueries(ConsoleTask):
  """Execute sophisticated queries about the pants target dependency graph.

  The queries must be loaded from JSON-formatted files; they are parsed by Conditions. Queries can
  be arbitrarily complicated and nested. Here is a simple example that finds untested
  java_library targets: ::

      {
        "type": "java_library",
        "not": {
          "dependee": {
            "type": "java_tests"
          }
        }
      }

  Refer to graph_conditions.py for a full list of possible query conditions.
  """

  class QueryFailed(TaskError):
    """Raised when a query returns results when it isn't supposed to, or vice-versa."""

  _output_method = {
    'yaml': '_yaml_output_iter',
    'json': '_json_output_iter',
  }

  @classmethod
  def register_options(cls, register):
    super(GraphQueries, cls).register_options(register)
    register('--query-file', advanced=True, type=str, default='{}',
             help='Json file containing a list or dictionary specifying conditions. '
                  'For example, to find all junit tests named "int-test", you could use: '
                  '{"type": "java_tests", "name": "int-test"}. You can specify multiple conditions '
                  'using a list, eg [{"spec": "^service"}, {"spec": ":lib$"}])')
    register('--fail-if-empty', action='store_true', default=False,
             help='Causes this task to fail if the query returns no results.',)
    register('--fail-if-not-empty', action='store_true', default=False,
             help='Causes this task to fail if the query returns any results.',)
    register('--fail-fast-if-not-empty', action='store_true', default=False,
             help='If --fail-if-not-empty is set, causes the task to fail the first time it finds '
                  'a target matching the query.',)
    register('--format', choices=sorted(cls._output_method), default='yaml',
             help='Controls the output format. If yaml, the output will be "streaming" (each '
                  'target satisfying the query conditions will be output as it is found)',)

  def __init__(self, *vargs, **kwargs):
    super(GraphQueries, self).__init__(*vargs, **kwargs)

  def _satisfying_targets_iter(self, predicate, targets):
    # Using a generator to enable efficient fail-fast behavior, and incremental updates for
    # human-readable output.
    found_any = False
    for target in targets:
      if predicate(target):
        if self.get_options().fail_fast_if_not_empty:
          raise self.QueryFailed('Query unexpectedly returned target: {} (failing fast).'
                                 .format(target.address.spec))
        found_any = True
        yield target
    if found_any and self.get_options().fail_if_not_empty:
      raise self.QueryFailed('Query returned targets, when it was not supposed to find any.')
    if not found_any and self.get_options().fail_if_empty:
      raise self.QueryFailed('Query found no targets, when it was supposed to find some.')

  def _yaml_output_iter(self, conditions, targets):
    yield 'targets:'
    targets = sorted(targets, key=lambda t: t.address.spec)
    for target in self._satisfying_targets_iter(conditions, targets):
      yield '  - {}'.format(target.address.spec)

  def _json_output_iter(self, conditions, targets):
    spec_list = list(t.address.spec for t in self._satisfying_targets_iter(conditions, targets))
    yield json.dumps(spec_list, sort_keys=True, separators=(', ', ': '))

  def _get_or_load_conditions_data(self):
    json_path = self.get_options().query_file
    if json_path:
      if not os.path.exists(json_path):
        raise TaskError('Json query file does not exist: {}'.format(json_path))
      try:
        with open(json_path, 'r') as f:
          return json.loads(f.read())
      except Exception as e:
        raise TaskError('Unable to load query from json file: {}\n{}'.format(json_path, e))
    raise TaskError('Json --query-file not provided.')

  def build_conditions(self, conditions=None):
    if conditions is None:
      conditions = self._get_or_load_conditions_data()
    if not isinstance(conditions, list):
      conditions = [conditions]
    conditions = map(Conditions, conditions)
    return lambda target: all(predicate(self.context, target) for predicate in conditions)

  def console_output(self, targets):
    conditions = self.build_conditions()
    return getattr(self, self._output_method[self.get_options().format])(conditions, targets)
