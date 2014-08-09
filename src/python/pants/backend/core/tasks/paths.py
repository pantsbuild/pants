# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import copy

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError


class PathFinder(ConsoleTask):
  def __init__(self, *args, **kwargs):
    super(PathFinder, self).__init__(*args, **kwargs)
    self.log = self.context.log
    self.target_roots = self.context.target_roots

  @classmethod
  def _find_paths(cls, from_target, to_target, log):
    log.debug('Looking for all paths from %s to %s' % (from_target.address.reference(),
                                                       to_target.address.reference()))

    paths = cls._find_paths_rec(from_target, to_target)
    print('Found %d paths' % len(paths))
    print('')
    for path in paths:
      log.debug('\t[%s]' % ', '.join([target.address.reference() for target in path]))

  all_paths = defaultdict(lambda: defaultdict(list))
  @classmethod
  def _find_paths_rec(cls, from_target, to_target):
    if from_target == to_target:
      return [[from_target]]

    if from_target not in cls.all_paths or to_target not in cls.all_paths[from_target]:
      paths = []
      for dep in from_target.dependencies:
        for path in cls._find_paths_rec(dep, to_target):
          new_path = copy.copy(path)
          new_path.insert(0, from_target)
          paths.append(new_path)

      cls.all_paths[from_target][to_target] = paths

    return cls.all_paths[from_target][to_target]

  examined_targets = set()

  @classmethod
  def _find_path(cls, from_target, to_target, log):
    log.debug('Looking for path from %s to %s' % (from_target.address.reference(),
                                                  to_target.address.reference()))

    queue = [([from_target], 0)]
    while True:
      if not queue:
        print('no path found from %s to %s!' % (from_target.address.reference(),
                                                to_target.address.reference()))
        break

      path, indent = queue.pop(0)
      next_target = path[-1]
      if next_target in cls.examined_targets:
        continue
      cls.examined_targets.add(next_target)

      log.debug('%sexamining %s' % ('  ' * indent, next_target))

      if next_target == to_target:
        print('')
        for target in path:
          print('%s' % target.address.reference())
        break

      for dep in next_target.dependencies:
        queue.append((path + [dep], indent + 1))


class Path(PathFinder):
  def execute(self):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found %d)' % len(self.target_roots))

    self._find_path(self.target_roots[0], self.target_roots[1], self.log)


class Paths(PathFinder):
  def execute(self):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found %d)' % len(self.target_roots))

    self._find_paths(self.target_roots[0], self.target_roots[1], self.log)
