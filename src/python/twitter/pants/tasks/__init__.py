# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'John Sirois'

import cPickle
import hashlib
import inspect
import os

from collections import defaultdict
from contextlib import contextmanager
from optparse import OptionGroup, OptionParser

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_open, safe_rmtree

from twitter.pants import get_buildroot, is_internal
from twitter.pants.base import BuildFile, ParseContext
from twitter.pants.base.build_cache import BuildCache
from twitter.pants.targets import InternalTarget, Pants

# TODO(John Sirois): Break these classes into top-level files

class Products(object):
  class ProductMapping(object):
    """
      Maps products of a given type by target.  Its assumed that all products of a given type for
      a given target are emitted to a single base directory.
    """

    def __init__(self, typename):
      self.typename = typename
      self.by_target = defaultdict(lambda: defaultdict(list))

    def add(self, target, basedir, product_paths=None):
      """
        Adds a mapping of products for the given target, basedir pair.

        If product_paths are specified, these will over-write any existing mapping for this target.

        If product_paths is omitted, the current mutable list of mapped products for this target
        and basedir is returned for appending.
      """
      if product_paths is not None:
        self.by_target[target][basedir].extend(product_paths)
      else:
        return self.by_target[target][basedir]

    def get(self, target):
      """
        Returns the product mapping for the given target as a tuple of (basedir, products list).
        Can return None if there is no mapping for the given target.
      """
      return self.by_target.get(target)

    def __repr__(self):
      return 'ProductMapping(%s) {\n  %s\n}' % (self.typename, '\n  '.join(
        '%s => %s\n    %s' % (str(target), basedir, outputs)
                              for target, (basedir, outputs) in self.by_target.items()
      ))

  def __init__(self):
    self.products = {}
    self.predicates_for_type = defaultdict(list)

  def require(self, typename, predicate=None):
    """
      Registers a requirement that products of the given type by mapped.  If a target predicate is
      supplied, only targets matching the predicate are mapped.
    """
    if predicate:
      self.predicates_for_type[typename].append(predicate)
    return self.products.setdefault(typename, Products.ProductMapping(typename))

  def isrequired(self, typename):
    """
      Returns a predicate that selects targets required for the given type if mappings are
      required.  Otherwise returns None.
    """
    if typename not in self.products:
      return None
    def combine(first, second):
      return lambda target: first(target) or second(target)
    return reduce(combine, self.predicates_for_type[typename], lambda target: False)

  def get(self, typename):
    """Returns a ProductMapping for the given type name."""
    return self.require(typename)


class Context(object):
  class Log(object):
    def debug(self, msg): pass
    def info(self, msg): pass
    def warn(self, msg): pass

  def __init__(self, config, options, target_roots, log=None):
    self.config = config
    self.options = options
    self.target_roots = target_roots
    self.log = log or Context.Log()
    self._state = {}
    self.products = Products()

    self._targets = OrderedSet()
    for target in self.target_roots:
      target.walk(self._add_target)

    self.id = self.identify(self._targets)

  def identify(self, targets):
    id = hashlib.md5()
    for target in targets:
      id.update(target.id)
    return id.hexdigest()

  def __str__(self):
    return 'Context(id:%s, state:%s, targets:%s)' % (self.id, self.state, self.targets())

  def _add_target(self, target):
    self._targets.update(t for t in target.resolve())

  def add_target(self, build_dir, target_type, *args, **kwargs):
    target = self._do_in_context(lambda: target_type(*args, **kwargs), build_dir)
    self._add_target(target)
    return target

  def targets(self, predicate=None):
    return filter(predicate, self._targets)

  def dependants(self, predicate=None):
    core = set(self.targets(predicate))
    dependees = defaultdict(set)
    for target in self.targets(lambda t: not predicate(t)):
      if hasattr(target, 'dependencies'):
        for dependency in target.dependencies:
          if dependency in core:
            dependees[target].add(dependency)
    return dependees

  def resolve(self, spec):
    return self._do_in_context(lambda: Pants(spec).resolve())

  def _do_in_context(self, work, path=None):
    # TODO(John Sirois): eliminate the need for all the gymanstics needed to synthesize a target
    build_dir = path or self.config.getdefault('pants_workdir')
    build_path = os.path.join(build_dir, 'BUILD.pants')
    if not os.path.exists(build_path):
      with safe_open(build_path, 'w') as build_file:
        build_file.write('# dummy BUILD file generated by pants\n')

    return ParseContext(BuildFile(get_buildroot(), build_path)).do_in_context(work)

  @contextmanager
  def state(self, key, default=None):
    value = self._state.get(key, default)
    yield value
    self._state[key] = value


class TaskError(Exception):
  """Raised to indicate a task has failed."""


class TargetError(TaskError):
  """Raised to indicate a task has failed for a subset of targets"""
  def __init__(self, targets, *args, **kwargs):
    TaskError.__init__(self, *args, **kwargs)
    self.targets = targets


class Task(object):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    """
      Subclasses can add flags to the pants command line using the given option group.  Flag names
      should be created with mkflag([name]) to ensure flags are properly namespaced amongst other
      tasks.
    """

  EXTRA_DATA = 'extra.data'

  def __init__(self, context):
    self.context = context

    self._build_cache = context.config.get('tasks', 'build_cache')
    self._basedir = os.path.join(self._build_cache, self.__class__.__name__)
    self._extradata = os.path.join(self._basedir, Task.EXTRA_DATA)

  def invalidate(self, all=False):
    safe_rmtree(self._build_cache if all else self._basedir)

  def execute(self, targets):
    """
      Executes this task against the given targets which may be a subset of the current context
      targets.
    """

  def invalidate_for(self):
    """
      Subclasses can override and return an object that should be checked for changes when using
      changed to manage target invalidation.  If the pickled form of returned object changes
      between runs all targets will be invalidated.
    """

  class CacheManager(object):
    """
      Manages cache checks, updates and invalidation keeping track of basic change and invalidation
      statistics.
    """
    def __init__(self, cache, targets, only_buildfiles):
      self._cache = cache
      self._only_buildfiles = only_buildfiles
      self._targets = set(targets)

      self.changed_files = 0
      self.invalidated_files = 0
      self.invalidated_targets = 0
      self.foreign_invalidated_targets = 0
      self.changed = defaultdict(list)

    def check_content(self, identifier, files):
      """
        Checks if identified content has changed and invalidates it if so.

        :id An identifier for the tracked content.
        :files The files containing the content to track changes for.
        :returns: The cache key for this content.
      """
      cache_key = self._cache.key_for(identifier, files)
      if self._cache.needs_update(cache_key):
        return cache_key

    def check(self, target):
      """Checks if a target has changed and invalidates it if so."""
      cache_key = self._key_for(target)
      if self._cache.needs_update(cache_key):
        self._invalidate(target, cache_key)

    def update(self, cache_key):
      """Mark a changed or invalidated target as successfully processed."""
      self._cache.update(cache_key)

    def invalidate(self, target, cache_key=None):
      """Forcefully mark a target as changed."""
      self._invalidate(target, cache_key or self._key_for(target), indirect=True)

    def _key_for(self, target):
      if self._only_buildfiles:
        absolute_sources = [target.address.buildfile.full_path]
      else:
        absolute_sources = sorted(target.expand_files(recursive=False))
      return self._cache.key_for(target.id, absolute_sources)

    def _invalidate(self, target, cache_key, indirect=False):
      if target in self._targets:
        self.changed[target].append(cache_key)
        if indirect:
          self.invalidated_files += len(cache_key.sources)
          self.invalidated_targets += 1
        else:
          self.changed_files += len(cache_key.sources)
      else:
        # invalidate a target to be processed in a subsequent round - this handles goal groups
        self._cache.invalidate(cache_key)
        self.foreign_invalidated_targets += 1


  @contextmanager
  def changed(self, targets, only_buildfiles=False, invalidate_dependants=False):
    """
      Yields an iterable over the targets that have changed since the last check to a with block.
      If no exceptions are thrown by work in the block, the cache is updated for the targets,
      otherwise if a TargetError is thrown by the work in the block all targets except those in the
      TargetError are cached.

      :targets The targets to check for changes.
      :only_buildfiles If True, then just the target's BUILD files are checked for changes.
      :invalidate_dependants If True then any targets depending on changed targets are invalidated
      :returns: the subset of targets that have changed
    """

    safe_mkdir(self._basedir)
    cache_manager = Task.CacheManager(BuildCache(self._basedir), targets, only_buildfiles)

    check = self.invalidate_for()
    if check is not None:
      with safe_open(self._extradata, 'w') as pickle:
        cPickle.dump(check, pickle)

      cache_key = cache_manager.check_content(Task.EXTRA_DATA, [self._extradata])
      if cache_key:
        self.context.log.debug('invalidating all targets for %s' % self.__class__.__name__)
        for target in targets:
          cache_manager.invalidate(target, cache_key)

    for target in targets:
      cache_manager.check(target)

    if invalidate_dependants and cache_manager.changed:
      for target in (self.context.dependants(lambda t: t in cache_manager.changed.keys())).keys():
        cache_manager.invalidate(target)

    if invalidate_dependants:
      if cache_manager.foreign_invalidated_targets:
        self.context.log.info('Invalidated %d dependant targets '
                              'for the next round' % cache_manager.foreign_invalidated_targets)

      if cache_manager.changed_files:
        msg = 'Operating on %d files in %d changed targets' % (
          cache_manager.changed_files,
          len(cache_manager.changed) - cache_manager.invalidated_targets
        )
        if cache_manager.invalidated_files:
          msg += ' and %d files in %d invalidated dependant targets' % (
            cache_manager.invalidated_files,
            cache_manager.invalidated_targets
          )
        self.context.log.info(msg)
    elif cache_manager.changed_files:
      self.context.log.info('Operating on %d files in %d changed targets' % (
        cache_manager.changed_files,
        len(cache_manager.changed)
      ))

    try:
      yield cache_manager.changed.keys()
      for cache_keys in cache_manager.changed.values():
        for cache_key in cache_keys:
          cache_manager.update(cache_key)
    except TargetError as e:
      for target, cache_keys in cache_manager.changed.items():
        if target not in e.targets:
          for cache_key in cache_keys:
            cache_manager.update(cache_key)


class Group(object):
  @staticmethod
  def execute(phase, tasks_by_goal, context, executed, timer=None):
    """Executes the named phase against the current context tracking goal executions in executed."""

    def execute_task(name, task, targets):
      """Execute and time a single goal that has had all of its dependencies satisfied."""
      start = timer.now() if timer else None
      try:
        task.execute(targets)
      finally:
        elapsed = timer.now() - start if timer else None
        if phase not in executed:
          executed[phase] = OrderedDict()
        if elapsed:
          phase_timings = executed[phase]
          if name not in phase_timings:
            phase_timings[name] = []
          phase_timings[name].append(elapsed)

    if phase not in executed:
      # Satisfy dependencies first
      goals = phase.goals()
      if not goals:
        raise TaskError('No goals installed for phase %s' % phase)

      for goal in goals:
        for dependency in goal.dependencies:
          Group.execute(dependency, tasks_by_goal, context, executed, timer=timer)

      runqueue = []
      goals_by_group = {}
      for goal in goals:
        if goal.group:
          group_name = goal.group.name
          if group_name not in goals_by_group:
            group_goals = [goal]
            runqueue.append((group_name, group_goals))
            goals_by_group[group_name] = group_goals
          else:
            goals_by_group[group_name].append(goal)
        else:
          runqueue.append((None, [goal]))

      for group_name, goals in runqueue:
        if not group_name:
          goal = goals[0]
          context.log.info('[%s:%s]' % (phase, goal.name))
          execute_task(goal.name, tasks_by_goal[goal], context.targets())
        else:
          for chunk in Group.create_chunks(context, goals):
            def in_chunk(target):
              return target in chunk
            for goal in goals:
              task = tasks_by_goal[goal]
              def is_goal_chunk(target):
                return in_chunk(target) and goal.group.predicate(target)
              goal_chunk = OrderedSet(context.targets(predicate=is_goal_chunk))
              if len(goal_chunk) > 0:
                context.log.info('[%s:%s:%s]' % (phase, group_name, goal.name))
                execute_task(goal.name, task, goal_chunk)

  @staticmethod
  def create_chunks(context, goals):
    def discriminator(target):
      for i, goal in enumerate(goals):
        if goal.group.predicate(target):
          return i
      return 'other'

    # TODO(John Sirois): coalescing should be made available in another spot, InternalTarget is jvm
    # specific, and all we care is that the Targets have dependencies defined
    coalesced = InternalTarget.coalesce_targets(context.targets(is_internal), discriminator)
    coalesced = list(reversed(coalesced))

    def not_internal(target):
      return not is_internal(target)
    rest = OrderedSet(context.targets(not_internal))

    chunks = [rest] if rest else []
    flavor = None
    chunk_start = 0
    for i, target in enumerate(coalesced):
      target_flavor = discriminator(target)
      if target_flavor != flavor and i > chunk_start:
        chunks.append(OrderedSet(coalesced[chunk_start:i]))
        chunk_start = i
      flavor = target_flavor
    if chunk_start < len(coalesced):
      chunks.append(OrderedSet(coalesced[chunk_start:]))

    context.log.debug('::: created chunks(%d)' % len(chunks))
    for i, chunk in enumerate(chunks):
      context.log.debug('  chunk(%d):\n    %s' % (i, '\n    '.join(str(t) for t in chunk)))

    return chunks

  def __init__(self, name, predicate):
    self.name = name
    self.predicate = predicate


class SingletonPhases(type):
  phases = dict()
  def __call__(cls, name):
    if name not in cls.phases:
      cls.phases[name] = super(SingletonPhases, cls).__call__(name)
    return cls.phases[name]


class Phase(object):
  __metaclass__ = SingletonPhases

  _goals_by_phase = defaultdict(list)

  @staticmethod
  def setup_parser(parser, args, phases):
    def do_setup_parser(phase, setup):
      for goal in phase.goals():
        if goal not in setup:
          setup.add(goal)
          for dep in goal.dependencies:
            do_setup_parser(dep, setup)
          goal.setup_parser(phase, parser, args)

    setup = set()
    for phase in phases:
      do_setup_parser(phase, setup)

  @staticmethod
  def attempt(context, phases, timer=None):
    """
      Attempts to reach the goals for the supplied phases, optionally recording phase timings and
      then logging then when all specified phases have completed.
    """

    start = timer.now() if timer else None
    executed = OrderedDict()

    # I'd rather do this in a finally block below, but some goals os.fork and each of these cause
    # finally to run, printing goal timings multiple times instead of once at the end.
    def print_timings():
      if timer:
        timer.log('Timing report')
        timer.log('=============')
        for phase, timings in executed.items():
          phase_time = None
          for goal, times in timings.items():
            if len(times) > 1:
              timer.log('[%(phase)s:%(goal)s(%(numsteps)d)] %(timings)s -> %(total).3fs' % {
                'phase': phase,
                'goal': goal,
                'numsteps': len(times),
                'timings': ','.join('%.3fs' % time for time in times),
                'total': sum(times)
              })
            else:
              timer.log('[%(phase)s:%(goal)s] %(total).3fs' % {
                'phase': phase,
                'goal': goal,
                'total': sum(times)
              })
            if not phase_time:
              phase_time = 0
            phase_time += sum(times)
          if len(timings) > 1:
            timer.log('[%(phase)s] total: %(total).3fs' % {
              'phase': phase,
              'total': phase_time
            })
        elapsed = timer.now() - start
        timer.log('total: %.3fs' % elapsed)

    try:
      # Prepare tasks
      tasks_by_goal = {}
      def prepare_tasks(phase):
        for goal in phase.goals():
          if goal not in tasks_by_goal:
            for dependency in goal.dependencies:
              prepare_tasks(dependency)
            task = goal.prepare(context)
            tasks_by_goal[goal] = task

      for phase in phases:
        prepare_tasks(phase)

      # Execute phases
      for phase in phases:
        Group.execute(phase, tasks_by_goal, context, executed, timer=timer)

      print_timings()
      return 0
    except TaskError as e:
      message = '%s' % e
      if message:
        print '\nFAILURE: %s\n' % e
      else:
        print '\nFAILURE\n'
      print_timings()
      return 1

  @staticmethod
  def execute(context, *names):
    parser = OptionParser()
    phases = [Phase(name) for name in names]
    Phase.setup_parser(parser, [], phases)
    options, _ = parser.parse_args([])
    context = Context(context.config, options, context.target_roots, context.log)
    return Phase.attempt(context, phases)

  @staticmethod
  def all():
    """Returns all registered goals as a sorted sequence of phase, goals tuples."""
    return sorted(Phase._goals_by_phase.items(), key=lambda (phase, goals): phase.name)

  def __init__(self, name):
    self.name = name
    self.description = None

  def with_description(self, description):
    self.description = description

  def install(self, goal, first=False, replace=False):
    g = self.goals()
    if replace:
      del g[:]
    if first:
      g.insert(0, goal)
    else:
      g.append(goal)

  def goals(self):
    return Phase._goals_by_phase[self]

  def __repr__(self):
    return self.name


class Goal(object):
  def __init__(self, name, action, group=None, dependencies=None):
    self.name = name
    self.group = group
    self.dependencies = [Phase(d) for d in dependencies] if dependencies else []

    if type(action) == type and issubclass(action, Task):
      self._task = action
    else:
      args, varargs, keywords, defaults = inspect.getargspec(action)
      if varargs or keywords or defaults:
        raise TaskError('Invalid action supplied, cannot accept varargs, keywords or defaults')
      if len(args) > 2:
        raise TaskError('Invalid action supplied, must accept 0, 1, or 2 args')

      class FuncTask(Task):
        def __init__(self, context):
          Task.__init__(self, context)

          if not args:
            self.action = lambda targets: action()
          elif len(args) == 1:
            self.action = lambda targets: action(targets)
          elif len(args) == 2:
            self.action = lambda targets: action(self.context, targets)
          else:
            raise AssertionError('Unexpected fallthrough')

        def execute(self, targets):
          self.action(targets)

      self._task = FuncTask

  def setup_parser(self, phase, parser, args):
    """Allows a task to add its command line args to the global sepcification."""
    def namespace(sep):
      phase_leader = phase.goals() == [self] or self.name == phase.name
      return self.name if phase_leader else '%s%s%s' % (phase.name, sep, self.name)

    group = OptionGroup(parser, title = namespace(':'))

    def mkflag(arg_name, negate=False):
      return '--%s%s-%s' % ('no-' if negate else '', namespace('-'), arg_name)

    def set_bool(option, opt_str, value, parser):
      setattr(parser.values, option.dest, not opt_str.startswith("--no"))
    mkflag.set_bool = set_bool

    self._task.setup_parser(group, args, mkflag)

    if group.option_list:
      parser.add_option_group(group)

  def prepare(self, context):
    """Prepares a Task that can be executed to achieve this goal."""
    return self._task(context)

  def install(self, phase=None, first=False, replace=False):
    """
      Installs this goal in the specified phase (or a new phase with the same name as this Goal),
      appending to any pre-existing goals unless first=True in which case it is installed as the
      first goal in the phase.  If replace=True then this goal replaces all others for the phase.
      The phase this goal is installed in is returned.
    """
    phase = Phase(phase or self.name)
    phase.install(self, first, replace)
    return phase


from twitter.pants.tasks.config import Config

__all__ = (
  'Config',
  'Context',
  'Goal',
  'Group',
  'Phase'
  'Task',
  'TaskError',
  'TargetError'
)
