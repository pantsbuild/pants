# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
from collections import deque

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError
from pants.util.strutil import pluralize


def format_path(path):
  return '[{}]'.format(', '.join([target.address.reference() for target in path]))


def find_paths_breadth_first(from_target, to_target, log):
  """Yields the paths between from_target to to_target if they exist.

  The paths are returned ordered by length, shortest first.
  If there are cycles, it checks visited edges to prevent recrossing them."""
  log.debug('Looking for all paths from {} to {}'.format(from_target.address.reference(),
                                                         to_target.address.reference()))

  if from_target == to_target:
    yield [from_target]
    return

  visited_edges = set()
  to_walk_paths = deque([[from_target]])
  while len(to_walk_paths) > 0:
    cur_path = to_walk_paths.popleft()
    target = cur_path[-1]

    if len(cur_path) > 1:
      prev_target = cur_path[-2]
    else:
      prev_target = None
    current_edge = (prev_target, target)

    if current_edge not in visited_edges:
      for dep in target.dependencies:
        dep_path = cur_path + [dep]
        if dep == to_target:
          yield dep_path
        else:
          to_walk_paths.append(dep_path)
      visited_edges.add(current_edge)


class PathFinder(ConsoleTask):
  def __init__(self, *args, **kwargs):
    super(PathFinder, self).__init__(*args, **kwargs)
    self.log = self.context.log
    self.target_roots = self.context.target_roots

  def validate_target_roots(self):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found {})'.format(len(self.target_roots)))


class Path(PathFinder):
  """Find a dependency path from one target to another."""

  def console_output(self, ignored_targets):
    self.validate_target_roots()

    from_target = self.target_roots[0]
    to_target = self.target_roots[1]

    for path in find_paths_breadth_first(from_target, to_target, self.log):
      yield format_path(path)
      break
    else:
      yield 'No path found from {} to {}!'.format(from_target.address.reference(),
                                                  to_target.address.reference())


class Paths(PathFinder):
  """Find all dependency paths from one target to another."""

  def console_output(self, ignored_targets):
    self.validate_target_roots()
    from_target = self.target_roots[0]
    to_target = self.target_roots[1]

    paths = list(find_paths_breadth_first(from_target, to_target, self.log))
    yield 'Found {}'.format(pluralize(len(paths), 'path'))
    if paths:
      yield ''
      for path in paths:
        yield '\t{}'.format(format_path(path))
