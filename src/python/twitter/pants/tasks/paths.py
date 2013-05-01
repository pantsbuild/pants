__author__ = 'ryan'

from twitter.common.lang import Compatibility
from twitter.pants import get_buildroot
from twitter.pants.base import Address, Target
from twitter.pants.tasks import Task, TaskError

class PathFinder(Task):

  def __init__(self, context):
    Task.__init__(self, context)
    self.log = context.log
    self.target_roots = context.target_roots

  @classmethod
  def some_path(cls, from_str, to_str, log):
    return cls._find_paths(from_str, to_str, log, find_all=False)

  @classmethod
  def all_paths(cls, from_str, to_str, log):
    return cls._find_paths(from_str, to_str, log, find_all=True)

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
  def _find_paths(cls, from_target, to_target, log, find_all):
    from_target, to_target = cls._coerce_to_targets(from_target, to_target)

    log.debug('Looking for path from %s to %s' % (from_target.address.reference(), to_target.address.reference()))

    paths_found = False

    queue = [([from_target], 0)]
    while True:
      if not queue:
        if not paths_found:
          print 'no path found from %s to %s!' % (from_target.address.reference(), to_target.address.reference())
        break

      path, indent = queue.pop(0)
      next_target = path[-1]
      log.debug('%sexamining %s' % ('  ' * indent, next_target))

      if next_target == to_target:
        if paths_found:
          print ''
        else:
          paths_found = True
        for target in path:
          print '%s' % target.address.reference()
        if find_all:
          continue
        else:
          break

      if hasattr(next_target, 'dependency_addresses'):
        for address in next_target.dependency_addresses:
          dep = Target.get(address)
          queue.append((path + [dep], indent + 1))


class Path(PathFinder):

  def execute(self, targets):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found %d)' % len(self.target_roots))

    self.some_path(self.target_roots[0], self.target_roots[1], self.log)

class Paths(PathFinder):

  def execute(self, targets):
    if len(self.target_roots) != 2:
      raise TaskError('Specify two targets please (found %d)' % len(self.target_roots))

    self.all_paths(self.target_roots[0], self.target_roots[1], self.log)
