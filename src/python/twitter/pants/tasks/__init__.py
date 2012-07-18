try:
  import cPickle as pickle
except ImportError:
  import pickle

from collections import defaultdict
from contextlib import contextmanager
import hashlib
import os

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_rmtree, safe_mkdir, safe_open

from twitter.pants.base.build_cache import BuildCache, NO_SOURCES, TARGET_SOURCES
from twitter.pants.targets import JarDependency


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

  def invalidate_for_files(self):
    """
      Subclasses can override and return a list of full paths to extra files that should be checked
      for changes when using changed to manage target invalidation. This is useful for tracking
      changes to pre-built build tools, e.g., the thrift compiler.
    """

  class CacheManager(object):
    """
      Manages cache checks, updates and invalidation keeping track of basic change and invalidation
      statistics.
    """
    def __init__(self, cache, targets, only_externaldeps):
      self._cache = cache
      self._targets = set(targets)
      self._sources = NO_SOURCES if only_externaldeps else TARGET_SOURCES

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
      if cache_key and self._cache.needs_update(cache_key):
        self._invalidate(target, cache_key)

    def update(self, cache_key):
      """Mark a changed or invalidated target as successfully processed."""
      self._cache.update(cache_key)

    def invalidate(self, target, cache_key=None):
      """Forcefully mark a target as changed."""
      self._invalidate(target, cache_key or self._key_for(target), indirect=True)

    def _key_for(self, target):
      return self._cache.key_for_target(
        target,
        sources=self._sources,
        fingerprint_extra=lambda sha: self._fingerprint_jardeps(target, sha)
      )

    _JAR_HASH_KEYS = (
      'org',
      'name',
      'rev',
      'force',
      'excludes',
      'transitive',
      'ext',
      'url',
      '_configurations'
    )

    def _fingerprint_jardeps(self, target, sha):
      internaltargets = OrderedSet()
      alltargets = OrderedSet()
      def fingerprint_external(target):
        internaltargets.add(target)
        if hasattr(target, 'dependencies'):
          alltargets.update(target.dependencies)
      target.walk(fingerprint_external)

      for external_target in alltargets - internaltargets:
        # TODO(John Sirois): Hashing on external targets should have a formal api - we happen to
        # know jars are special and python requirements __str__ works for this purpose.
        if isinstance(external_target, JarDependency):
          jarid = ''
          for key in Task.CacheManager._JAR_HASH_KEYS:
            jarid += str(getattr(external_target, key))
          sha.update(jarid)
        else:
          sha.update(str(external_target))

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
  def changed(self, targets, only_buildfiles=False, invalidate_dependants=False, invalidate_globally=False):
    """
      Yields an iterable over the targets that have changed since the last check to a with block.
      If no exceptions are thrown by work in the block, the cache is updated for the targets,
      otherwise if a TargetError is thrown by the work in the block all targets except those in the
      TargetError are cached.

      :targets The targets to check for changes.
      :only_buildfiles If True, then just the target's BUILD files are checked for changes.
      :invalidate_dependants If True then any targets depending on changed targets are invalidated
      :invalidate_globally If True then if any target has changed, all targets are invalidated.
      :returns: the subset of targets that have changed
    """

    safe_mkdir(self._basedir)
    cache_manager = Task.CacheManager(BuildCache(self._basedir), targets, only_buildfiles)

    # invalidate_for() may return an iterable that isn't a set, so we ensure a set here.
    check = self.invalidate_for()
    if check is not None:
      check = set(check)

    check_files = self.invalidate_for_files()
    if check_files is not None:
      check_files = set(check_files)
      if check is None:
        check = set()
      for f in check_files:
        sha = hashlib.sha1()
        with open(f, "rb") as fd:
          sha.update(fd.read())
        check = check.add(sha.hexdigest())

    if check is not None:
      extradata_id = self.context.maybe_readable_identify(targets) + '.extra.data'
      extradata = os.path.join(self._basedir, extradata_id)
      with safe_open(extradata, 'w') as pickled:
        pickle.dump(check, pickled)

      cache_key = cache_manager.check_content(extradata_id, [extradata])
      if cache_key:
        self.context.log.debug('invalidating all targets for %s' % self.__class__.__name__)
        for target in targets:
          cache_manager.invalidate(target, cache_key)

    for target in targets:
      cache_manager.check(target)

    if invalidate_dependants and cache_manager.changed:
      for target in (self.context.dependants(lambda t: t in cache_manager.changed.keys())).keys():
        cache_manager.invalidate(target)

    if invalidate_globally and cache_manager.changed:
      for target in targets:
        cache_manager.invalidate(target)

    if invalidate_dependants or invalidate_globally:
      if cache_manager.foreign_invalidated_targets:
        self.context.log.info('Invalidated %d dependant targets '
                              'for the next round' % cache_manager.foreign_invalidated_targets)

      if cache_manager.changed_files:
        msg = 'Operating on %d files in %d changed targets' % (
          cache_manager.changed_files,
          len(cache_manager.changed)
        )
        if cache_manager.invalidated_files:
          if invalidate_globally:
            invalidation_msg = 'globally invalidated'
          else:
            invalidation_msg = 'invalidated dependant'
          msg += ' and %d files in %d %s targets' % (
            cache_manager.invalidated_files,
            cache_manager.invalidated_targets,
            invalidation_msg
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

__all__ = (
  'TaskError',
  'TargetError',
  'Task'
)
