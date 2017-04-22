# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import sys
from hashlib import sha1

from pants.build_graph.build_graph import sort_targets
from pants.build_graph.target import Target
from pants.invalidation.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.util.dirutil import relative_symlink, safe_delete, safe_mkdir, safe_rmtree
from pants.util.memo import memoized_method


class VersionedTargetSet(object):
  """Represents a list of targets, a corresponding CacheKey, and a flag determining whether the
  list of targets is currently valid.

  When invalidating a single target, this can be used to represent that target as a singleton.
  When checking the artifact cache, this can also be used to represent a list of targets that are
  built together into a single artifact.
  """

  class IllegalResultsDir(Exception):
    """Indicate a problem interacting with a versioned target results directory."""

  @staticmethod
  def from_versioned_targets(versioned_targets):
    """
    :API: public
    """
    first_target = versioned_targets[0]
    cache_manager = first_target._cache_manager

    # Quick sanity check; all the versioned targets should have the same cache manager.
    # TODO(ryan): the way VersionedTargets store their own links to a single CacheManager instance
    # feels hacky; see if there's a cleaner way for callers to handle awareness of the CacheManager.
    for versioned_target in versioned_targets:
      if versioned_target._cache_manager != cache_manager:
        raise ValueError("Attempting to combine versioned targets {} and {} with different"
                         " CacheManager instances: {} and {}".format(first_target, versioned_target,
                                                                 cache_manager,
                                                                 versioned_target._cache_manager))
    return VersionedTargetSet(cache_manager, versioned_targets)

  def __init__(self, cache_manager, versioned_targets):
    self._cache_manager = cache_manager
    self.versioned_targets = versioned_targets
    self.targets = [vt.target for vt in versioned_targets]

    # The following line is a no-op if cache_key was set in the VersionedTarget __init__ method.
    self.cache_key = CacheKeyGenerator.combine_cache_keys([vt.cache_key
                                                           for vt in versioned_targets])
    # NB: previous_cache_key may be None on the first build of a target.
    self.previous_cache_key = cache_manager.previous_key(self.cache_key)
    self.valid = self.previous_cache_key == self.cache_key

    if cache_manager.invalidation_report:
      cache_manager.invalidation_report.add_vts(cache_manager, self.targets, self.cache_key,
                                                self.valid, phase='init')

    self._results_dir = None
    self._current_results_dir = None
    self._previous_results_dir = None
    # True if the results_dir for this VT was created incrementally via clone of the
    # previous results_dir.
    self.is_incremental = False

  def update(self):
    self._cache_manager.update(self)

  def force_invalidate(self):
    # Note: This method isn't exposted as Public because the api is not yet
    # finalized, however it is currently used by Square for plugins.  There is
    # an open OSS issue to finalize this API.  Please take care when changing
    # until https://github.com/pantsbuild/pants/issues/2532 is resolved.
    self._cache_manager.force_invalidate(self)

  @property
  def has_results_dir(self):
    return self._results_dir is not None

  @property
  def has_previous_results_dir(self):
    return self._previous_results_dir is not None and os.path.isdir(self._previous_results_dir)

  @property
  def results_dir(self):
    """The directory that stores results for these targets.

    The results_dir is represented by a stable symlink to the current_results_dir: consumers
    should generally prefer to access the stable directory.
    """
    if self._results_dir is None:
      raise ValueError('No results_dir was created for {}'.format(self))
    return self._results_dir

  @property
  def current_results_dir(self):
    """A unique directory that stores results for this version of these targets.
    """
    if self._current_results_dir is None:
      raise ValueError('No results_dir was created for {}'.format(self))
    return self._current_results_dir

  @property
  def previous_results_dir(self):
    """The directory that stores results for the previous version of these targets.

    Only valid if is_incremental is true.

    TODO: Exposing old results is a bit of an abstraction leak, because ill-behaved Tasks could
    mutate them.
    """
    if not self.has_previous_results_dir:
      raise ValueError('There is no previous_results_dir for: {}'.format(self))
    return self._previous_results_dir

  def ensure_legal(self):
    """Return True as long as the state does not break any internal contracts."""
    # Do our best to provide complete feedback, it's easy to imagine the frustration of flipping between error states.
    if self._results_dir:
      errors = ''
      if not os.path.islink(self._results_dir):
        errors += '\nThe results_dir is no longer a symlink:\n\t* {}'.format(self._results_dir)
      if not os.path.isdir(self._current_results_dir):
        errors += '\nThe current_results_dir directory was not found\n\t* {}'.format(self._current_results_dir)
      if errors:
        raise self.IllegalResultsDir(
          '\nThe results_dirs state should not be manually cleaned or recreated by tasks.\n{}'.format(errors)
        )
    return True

  def live_dirs(self):
    """Yields directories that must exist for this VersionedTarget to function."""
    # The only caller of this function is the workdir cleaning pipeline. It is not clear that the previous_results_dir
    # should be returned for that purpose. And, by the time this is called, the contents have already been copied.
    if self.has_results_dir:
      yield self.results_dir
      yield self.current_results_dir
      if self.has_previous_results_dir:
        yield self.previous_results_dir

  @memoized_method
  def _target_to_vt(self):
    return {vt.target: vt for vt in self.versioned_targets}

  def __repr__(self):
    return 'VTS({}, {})'.format(','.join(target.address.spec for target in self.targets),
                                'valid' if self.valid else 'invalid')


class VersionedTarget(VersionedTargetSet):
  """This class represents a singleton VersionedTargetSet, and has links to VersionedTargets that
  the wrapped target depends on (after having resolved through any "alias" targets.

  :API: public
  """

  def __init__(self, cache_manager, target, cache_key):
    """
    :API: public
    """
    if not isinstance(target, Target):
      raise ValueError("The target {} must be an instance of Target but is not.".format(target.id))

    self.target = target
    self.cache_key = cache_key
    # Must come after the assignments above, as they are used in the parent's __init__.
    super(VersionedTarget, self).__init__(cache_manager, [self])
    self.id = target.id

  def create_results_dir(self):
    """Ensure that the empty results directory and a stable symlink exist for these versioned targets."""
    self._current_results_dir = self._cache_manager.results_dir_path(self.cache_key, stable=False)
    self._results_dir = self._cache_manager.results_dir_path(self.cache_key, stable=True)

    if not self.valid:
      # Clean the workspace for invalid vts.
      safe_mkdir(self._current_results_dir, clean=True)
      relative_symlink(self._current_results_dir, self._results_dir)
    self.ensure_legal()

  def copy_previous_results(self, root_dir):
    """Use the latest valid results_dir as the starting contents of the current results_dir.

    Should be called after the cache is checked, since previous_results are not useful if there is a cached artifact.
    """
    # TODO(mateo): An immediate followup removes the root_dir param, it is identical to the task.workdir.
    # TODO(mateo): This should probably be managed by the task, which manages the rest of the incremental support.
    if not self.previous_cache_key:
      return None
    previous_path = self._cache_manager.results_dir_path(self.previous_cache_key, stable=False)
    if os.path.isdir(previous_path):
      self.is_incremental = True
      safe_rmtree(self._current_results_dir)
      shutil.copytree(previous_path, self._current_results_dir)
    safe_mkdir(self._current_results_dir)
    relative_symlink(self._current_results_dir, self.results_dir)
    # Set the self._previous last, so that it is only True after the copy completed.
    self._previous_results_dir = previous_path

  def __repr__(self):
    return 'VT({}, {})'.format(self.target.id, 'valid' if self.valid else 'invalid')


class InvalidationCheck(object):
  """The result of calling check() on a CacheManager.

  Each member is a list of VersionedTargetSet objects.  Sorting of the targets depends
  on how you order the InvalidationCheck from the InvalidationCacheManager.

  Tasks may need to perform no, some or all operations on either of these, depending on how they
  are implemented.
  """

  def __init__(self, all_vts, invalid_vts):
    """
    :API: public
    """

    # All the targets, valid and invalid.
    self.all_vts = all_vts

    # Just the invalid targets.
    self.invalid_vts = invalid_vts


class InvalidationCacheManager(object):
  """Manages cache checks, updates and invalidation keeping track of basic change
  and invalidation statistics.
  Note that this is distinct from the ArtifactCache concept, and should probably be renamed.
  """

  class CacheValidationError(Exception):
    """Indicates a problem accessing the cache."""

  _STABLE_DIR_NAME = 'current'

  def __init__(self,
               results_dir_root,
               cache_key_generator,
               build_invalidator_dir,
               invalidate_dependents,
               fingerprint_strategy=None,
               invalidation_report=None,
               task_name=None,
               task_version=None,
               artifact_write_callback=lambda _: None):
    """
    :API: public
    """
    self._cache_key_generator = cache_key_generator
    self._task_name = task_name or 'UNKNOWN'
    self._task_version = task_version or 'Unknown_0'
    self._invalidate_dependents = invalidate_dependents
    self._invalidator = BuildInvalidator(build_invalidator_dir)
    self._fingerprint_strategy = fingerprint_strategy
    self._artifact_write_callback = artifact_write_callback
    self.invalidation_report = invalidation_report

    # Create the task-versioned prefix of the results dir, and a stable symlink to it
    # (useful when debugging).
    self._results_dir_prefix = os.path.join(results_dir_root,
                                            sha1(self._task_version).hexdigest()[:12])
    safe_mkdir(self._results_dir_prefix)
    stable_prefix = os.path.join(results_dir_root, self._STABLE_DIR_NAME)
    safe_delete(stable_prefix)
    relative_symlink(self._results_dir_prefix, stable_prefix)

  def update(self, vts):
    """Mark a changed or invalidated VersionedTargetSet as successfully processed."""
    for vt in vts.versioned_targets:
      vt.ensure_legal()
      if not vt.valid:
        self._invalidator.update(vt.cache_key)
        vt.valid = True
        self._artifact_write_callback(vt)
    if not vts.valid:
      vts.ensure_legal()
      self._invalidator.update(vts.cache_key)
      vts.valid = True
      self._artifact_write_callback(vts)

  def force_invalidate(self, vts):
    """Force invalidation of a VersionedTargetSet."""
    for vt in vts.versioned_targets:
      self._invalidator.force_invalidate(vt.cache_key)
      vt.valid = False
    self._invalidator.force_invalidate(vts.cache_key)
    vts.valid = False

  def check(self,
            targets,
            topological_order=False):
    """Checks whether each of the targets has changed and invalidates it if so.

    Returns a list of VersionedTargetSet objects (either valid or invalid). The returned sets
    'cover' the input targets, with one caveat: if the FingerprintStrategy
    opted out of fingerprinting a target because it doesn't contribute to invalidation, then that
    target will be excluded from all_vts and invalid_vts.

    Callers can inspect these vts and rebuild the invalid ones, for example.
    """
    all_vts = self.wrap_targets(targets, topological_order=topological_order)
    invalid_vts = filter(lambda vt: not vt.valid, all_vts)
    return InvalidationCheck(all_vts, invalid_vts)

  @property
  def task_name(self):
    return self._task_name

  def results_dir_path(self, key, stable):
    """Return a results directory path for the given key.

    :param key: A CacheKey to generate an id for.
    :param stable: True to use a stable subdirectory, false to use a portion of the cache key to
      generate a path unique to the key.
    """
    # TODO: Shorten cache_key hashes in general?
    return os.path.join(
      self._results_dir_prefix,
      key.id,
      self._STABLE_DIR_NAME if stable else sha1(key.hash).hexdigest()[:12]
    )

  def wrap_targets(self, targets, topological_order=False):
    """Wrap targets and their computed cache keys in VersionedTargets.

    If the FingerprintStrategy opted out of providing a fingerprint for a target, that target will not
    have an associated VersionedTarget returned.

    Returns a list of VersionedTargets, each representing one input target.
    """
    def vt_iter():
      if topological_order:
        target_set = set(targets)
        sorted_targets = [t for t in reversed(sort_targets(targets)) if t in target_set]
      else:
        sorted_targets = sorted(targets)
      for target in sorted_targets:
        target_key = self._key_for(target)
        if target_key is not None:
          yield VersionedTarget(self, target, target_key)
    return list(vt_iter())

  def previous_key(self, cache_key):
    return self._invalidator.previous_key(cache_key)

  def _key_for(self, target):
    try:
      return self._cache_key_generator.key_for_target(target,
                                                      transitive=self._invalidate_dependents,
                                                      fingerprint_strategy=self._fingerprint_strategy)
    except Exception as e:
      # This is a catch-all for problems we haven't caught up with and given a better diagnostic.
      # TODO(Eric Ayers): If you see this exception, add a fix to catch the problem earlier.
      exc_info = sys.exc_info()
      new_exception = self.CacheValidationError("Problem validating target {} in {}: {}"
                                                .format(target.id, target.address.spec_path, e))

      raise self.CacheValidationError, new_exception, exc_info[2]
