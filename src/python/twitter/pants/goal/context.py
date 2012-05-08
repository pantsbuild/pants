import hashlib
import os

from collections import defaultdict
from contextlib import contextmanager

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import Lock

from twitter.pants import SourceRoot
from twitter.pants.base import ParseContext
from twitter.pants.targets import Pants
from twitter.pants.goal.products import Products

class Context(object):
  """Contains the context for a single run of pants.

  Goal implementations can access configuration data from pants.ini and any flags they have exposed
  here as well as information about the targets involved in the run.

  Advanced uses of the context include adding new targets to it for upstream or downstream goals to
  operate on and mapping of products a goal creates to the targets the products are associated with.
  """

  class Log(object):
    def debug(self, msg): pass
    def info(self, msg): pass
    def warn(self, msg): pass

  def __init__(self, config, options, target_roots, lock=None, log=None):
    self._config = config
    self._options = options
    self._lock = lock or Lock.unlocked()
    self._log = log or Context.Log()
    self._state = {}
    self._products = Products()

    self.replace_targets(target_roots)

  @property
  def config(self):
    """Returns a Config object containing the configuration data found in pants.ini."""
    return self._config

  @property
  def options(self):
    """Returns the command line options parsed at startup."""
    return self._options

  @property
  def lock(self):
    """Returns the global pants run lock so a goal can release it if needed."""
    return self._lock

  @property
  def log(self):
    """Returns the preferred logger for goals to use."""
    return self._log

  @property
  def products(self):
    """Returns the Products manager for the current run."""
    return self._products

  @property
  def target_roots(self):
    """Returns the targets specified on the command line.

    This set is strictly a subset of all targets in play for the run as returned by self.targets().
    Note that for a command line invocation that uses wildcard selectors : or ::, the targets
    globbed by the wildcards are considered to be target roots.
    """
    return self._target_roots

  def identify(self, targets):
    id = hashlib.md5()
    for target in targets:
      id.update(target.id)
    return id.hexdigest()

  def __str__(self):
    return 'Context(id:%s, state:%s, targets:%s)' % (self.id, self.state, self.targets())

  def replace_targets(self, target_roots):
    """Replaces all targets in the context with the given roots and their transitive
    dependencies.
    """
    self._target_roots = target_roots
    self._targets = OrderedSet()
    for target in target_roots:
      self.add_target(target)
    self.id = self.identify(self._targets)

  def add_target(self, target):
    """Adds a target and its transitive dependencies to the run context.

    The target is not added to the target roots.
    """
    def add_targets(tgt):
      self._targets.update(tgt.resolve())
    target.walk(add_targets)

  def add_new_target(self, target_base, target_type, *args, **kwargs):
    """Creates a new target, adds it to the context and returns it.

    This method ensures the target resolves files against the given target_base, creating the
    directory if needed and registering a source root.
    """
    target = self._create_new_target(target_base, target_type, *args, **kwargs)
    self.add_target(target)
    return target

  def _create_new_target(self, target_base, target_type, *args, **kwargs):
    if not os.path.exists(target_base):
      os.makedirs(target_base)
    SourceRoot.register(target_base, target_type)
    with ParseContext.temp(target_base):
      return target_type(*args, **kwargs)

  def remove_target(self, target):
    """Removes the given Target object from the context completely if present."""
    if target in self.target_roots:
      self.target_roots.remove(target)
    self._targets.discard(target)

  def targets(self, predicate=None):
    """Selects targets in-play in this run from the target roots and their transitive dependencies.

    If specified, the predicate will be used to narrow the scope of targets returned.
    """
    return filter(predicate, self._targets)

  def dependants(self, on_predicate=None, from_predicate=None):
    """Returns  a map from targets that satisfy the from_predicate to targets they depend on that
      satisfy the on_predicate.
    """
    core = set(self.targets(on_predicate))
    dependees = defaultdict(set)
    for target in self.targets(from_predicate):
      if hasattr(target, 'dependencies'):
        for dependency in target.dependencies:
          if dependency in core:
            dependees[target].add(dependency)
    return dependees

  def resolve(self, spec):
    """Returns an iterator over the target(s) the given address points to."""
    with ParseContext.temp():
      return Pants(spec).resolve()

  @contextmanager
  def state(self, key, default=None):
    value = self._state.get(key, default)
    yield value
    self._state[key] = value
