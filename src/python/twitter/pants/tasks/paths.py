from __future__ import print_function
__author__ = 'ryan'

from collections import defaultdict
import copy

from twitter.common.lang import Compatibility
from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base import Address, Target
from twitter.pants.tasks import Task, TaskError

class PathFinder(Task):

  def __init__(self, context):
    Task.__init__(self, context)
    self.log = context.log
    self.target_roots = context.target_roots

  @classmethod
  def _coerce_to_targets(cls, from_str, to_str):
    if isinstance(from_str, Compatibility.string):
      if not isinstance(to_str, Compatibility.string):
        raise TaskError('Finding paths from string %s to non-string %s' % (from_str, str(to_str)))

      from_address = Address.parse(get_buildroot(), from_str)
      to_address = Address.parse(get_buildroot(), to_str)

      from_target = Target.get(from_address)
      to_target = Target.get(to_address)

      if not from_target:
        raise TaskError('Target %s doesn\'t exist' % from_address.reference())
      if not to_target:
        raise TaskError('Target %s doesn\'t exist' % to_address.reference())

      return from_target, to_target

    elif isinstance(to_str, Compatibility.string):
      raise TaskError('Finding paths from string %s to non-string %s' % (to_str, str(from_str)))
    return from_str, to_str

  @classmethod
  def _find_paths(cls, from_target, to_target, log):
    from_target, to_target = cls._coerce_to_targets(from_target, to_target)

    log.debug('Looking for all paths from %s to %s' % (from_target.address.reference(), to_target.address.reference()))

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
      if hasattr(from_target, 'dependency_addresses'):
        for address in from_target.dependency_addresses:
          dep = Target.get(address)
          for path in cls._find_paths_rec(dep, to_target):
            new_path = copy.copy(path)
            new_path.insert(0, from_target)
            paths.append(new_path)

      cls.all_paths[from_target][to_target] = paths

    return cls.all_paths[from_target][to_target]

  examined_targets = set()

  @classmethod
  def _find_path(cls, from_target, to_target, log):
    from_target, to_target = cls._coerce_to_targets(from_target, to_target)

    log.debug('Looking for path from %s to %s' % (from_target.address.reference(), to_target.address.reference()))

    queue = [([from_target], 0)]
    while True:
      if not queue:
        print('no path found from %s to %s!' % (from_target.address.reference(), to_target.address.reference()))
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

      if hasattr(next_target, 'dependency_addresses'):
        for address in next_target.dependency_addresses:
          dep = Target.get(address)
          queue.append((path + [dep], indent + 1))


class Path(PathFinder):

  def execute(self, targets):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found %d)' % len(self.target_roots))

    self._find_path(self.target_roots[0], self.target_roots[1], self.log)

class Paths(PathFinder):

  def execute(self, targets):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found %d)' % len(self.target_roots))

    self._find_paths(self.target_roots[0], self.target_roots[1], self.log)
