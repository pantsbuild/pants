# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import shutil
from builtins import map, str
from collections import defaultdict

from pex.interpreter import PythonInterpreter
from pex.package import EggPackage, Package, SourcePackage
from pex.resolver import resolve

from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TaskError
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


# TODO(wickman) Create a safer version of this and add to twitter.common.dirutil
def _safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


# TODO: Move under subsystems/ .
class PythonInterpreterCache(Subsystem):
  """Finds python interpreters on the local system."""
  options_scope = 'python-interpreter-cache'

  @classmethod
  def subsystem_dependencies(cls):
    return (super(PythonInterpreterCache, cls).subsystem_dependencies() +
            (PythonSetup, PythonRepos))

  class UnsatisfiableInterpreterConstraintsError(TaskError):
    """Indicates a python interpreter matching given constraints could not be located."""

  @staticmethod
  def _matches(interpreter, filters=()):
    return not filters or any(interpreter.identity.matches(filt) for filt in filters)

  @classmethod
  def _matching(cls, interpreters, filters=()):
    for interpreter in interpreters:
      if cls._matches(interpreter, filters=filters):
        yield interpreter

  @memoized_property
  def _python_setup(self):
    return PythonSetup.global_instance()

  @memoized_property
  def _python_repos(self):
    return PythonRepos.global_instance()

  @memoized_property
  def _cache_dir(self):
    cache_dir = self._python_setup.interpreter_cache_dir
    safe_mkdir(cache_dir)
    return cache_dir

  def partition_targets_by_compatibility(self, targets):
    """Partition targets by their compatibility constraints.

    :param targets: a list of `PythonTarget` objects
    :returns: (tgts_by_compatibilities, filters): a dict that maps compatibility constraints
      to a list of matching targets, the aggregate set of compatibility constraints imposed
      by the target set
    :rtype: (dict(str, list), set)
    """
    tgts_by_compatibilities = defaultdict(list)
    filters = set()

    for target in targets:
      if isinstance(target, PythonTarget):
        c = self._python_setup.compatibility_or_constraints(target)
        tgts_by_compatibilities[c].append(target)
        filters.update(c)
    return tgts_by_compatibilities, filters

  def select_interpreter_for_targets(self, targets):
    """Pick an interpreter compatible with all the specified targets."""

    tgts_by_compatibilities, total_filter_set = self.partition_targets_by_compatibility(targets)
    allowed_interpreters = set(self.setup(filters=total_filter_set))

    # Constrain allowed_interpreters based on each target's compatibility requirements.
    for compatibility in tgts_by_compatibilities:
      compatible_with_target = set(self._matching(allowed_interpreters, compatibility))
      allowed_interpreters &= compatible_with_target

    if not allowed_interpreters:
      # Create a helpful error message.
      unique_compatibilities = {tuple(c) for c in tgts_by_compatibilities.keys()}
      unique_compatibilities_strs = [','.join(x) for x in unique_compatibilities if x]
      tgts_by_compatibilities_strs = [t[0].address.spec for t in tgts_by_compatibilities.values()]
      raise self.UnsatisfiableInterpreterConstraintsError(
        'Unable to detect a suitable interpreter for compatibilities: {} '
        '(Conflicting targets: {})'.format(' && '.join(sorted(unique_compatibilities_strs)),
                                           ', '.join(tgts_by_compatibilities_strs)))
    # Return the lowest compatible interpreter.
    return min(allowed_interpreters)

  def _interpreter_from_path(self, path, filters=()):
    try:
      executable = os.readlink(os.path.join(path, 'python'))
      if not os.path.exists(executable):
        if os.path.dirname(path) == self._cache_dir:
          self._purge_interpreter(path)
        return None
    except OSError:
      return None
    interpreter = PythonInterpreter.from_binary(executable, include_site_extras=False)
    if self._matches(interpreter, filters=filters):
      return self._resolve(interpreter)
    return None

  def _setup_interpreter(self, interpreter, cache_target_path):
    with safe_concurrent_creation(cache_target_path) as safe_path:
      os.mkdir(safe_path)  # Parent will already have been created by safe_concurrent_creation.
      os.symlink(interpreter.binary, os.path.join(safe_path, 'python'))
      return self._resolve(interpreter, safe_path)

  def _setup_cached(self, filters=()):
    """Find all currently-cached interpreters."""
    for interpreter_dir in os.listdir(self._cache_dir):
      path = os.path.join(self._cache_dir, interpreter_dir)
      if os.path.isdir(path):
        pi = self._interpreter_from_path(path, filters=filters)
        if pi:
          logger.debug('Detected interpreter {}: {}'.format(pi.binary, str(pi.identity)))
          yield pi

  def _setup_paths(self, paths, filters=()):
    """Find interpreters under paths, and cache them."""
    for interpreter in self._matching(PythonInterpreter.all(paths), filters=filters):
      identity_str = str(interpreter.identity)
      cache_path = os.path.join(self._cache_dir, identity_str)
      pi = self._interpreter_from_path(cache_path, filters=filters)
      if pi is None:
        self._setup_interpreter(interpreter, cache_path)
        pi = self._interpreter_from_path(cache_path, filters=filters)
      if pi:
        yield pi

  def setup(self, filters=()):
    """Sets up a cache of python interpreters.

    :param filters: A sequence of strings that constrain the interpreter compatibility for this
      cache, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
      for requirements agnostic to interpreter class.
    :returns: A list of cached interpreters
    :rtype: list of :class:`pex.interpreter.PythonInterpreter`
    """
    # We filter the interpreter cache itself (and not just the interpreters we pull from it)
    # because setting up some python versions (e.g., 3<=python<3.3) crashes, and this gives us
    # an escape hatch.
    filters = filters if any(filters) else self._python_setup.interpreter_constraints
    setup_paths = self._python_setup.interpreter_search_paths
    logger.debug(
      'Initializing Python interpreter cache matching filters `{}` from paths `{}`'.format(
        ':'.join(filters), ':'.join(setup_paths)))

    interpreters = []
    def unsatisfied_filters():
      return [f for f in filters if len(list(self._matching(interpreters, [f]))) == 0]

    with OwnerPrintingInterProcessFileLock(path=os.path.join(self._cache_dir, '.file_lock')):
      interpreters.extend(self._setup_cached(filters=filters))
      if not interpreters or unsatisfied_filters():
        interpreters.extend(self._setup_paths(setup_paths, filters=filters))

    for filt in unsatisfied_filters():
      logger.debug('No valid interpreters found for {}!'.format(filt))

    matches = list(self._matching(interpreters, filters=filters))
    if len(matches) == 0:
      logger.debug('Found no valid interpreters!')

    logger.debug(
      'Initialized Python interpreter cache with {}'.format(', '.join([x.binary for x in matches])))
    return matches

  def _resolve(self, interpreter, interpreter_dir=None):
    """Resolve and cache an interpreter with a setuptools and wheel capability."""
    interpreter = self._resolve_interpreter(interpreter, interpreter_dir,
                                            self._python_setup.setuptools_requirement())
    if interpreter:
      return self._resolve_interpreter(interpreter, interpreter_dir,
                                       self._python_setup.wheel_requirement())

  def _resolve_interpreter(self, interpreter, interpreter_dir, requirement):
    """Given a :class:`PythonInterpreter` and a requirement, return an interpreter with the
    capability of resolving that requirement or ``None`` if it's not possible to install a
    suitable requirement.

    If interpreter_dir is unspecified, operates on the default location.
    """
    if interpreter.satisfies([requirement]):
      return interpreter

    if not interpreter_dir:
      interpreter_dir = os.path.join(self._cache_dir, str(interpreter.identity))

    target_link = os.path.join(interpreter_dir, requirement.key)
    bdist = self._resolve_and_link(interpreter, requirement, target_link)
    if bdist:
      return interpreter.with_extra(bdist.name, bdist.raw_version, bdist.path)
    else:
      logger.debug('Failed to resolve requirement {} for {}'.format(requirement, interpreter))

  def _resolve_and_link(self, interpreter, requirement, target_link):
    # Short-circuit if there is a local copy.
    if os.path.exists(target_link) and os.path.exists(os.path.realpath(target_link)):
      bdist = Package.from_href(os.path.realpath(target_link))
      if bdist.satisfies(requirement):
        return bdist

    # Since we're resolving to bootstrap a bare interpreter, we won't have wheel available.
    # Explicitly set the precedence to avoid resolution of wheels or distillation of sdists into
    # wheels.
    precedence = (EggPackage, SourcePackage)
    resolved_dists = resolve(requirements=[requirement],
                             fetchers=self._python_repos.get_fetchers(),
                             interpreter=interpreter,
                             # The local interpreter cache is, by definition, composed of
                             #  interpreters for the 'current' platform.
                             platform='current',
                             context=self._python_repos.get_network_context(),
                             precedence=precedence)
    if not resolved_dists:
      return None

    assert len(resolved_dists) == 1, ('Expected exactly 1 distribution to be resolved for {}, '
                                     'found:\n\t{}'.format(requirement,
                                                           '\n\t'.join(map(str, resolved_dists))))

    dist_location = resolved_dists[0].distribution.location
    target_location = os.path.join(os.path.dirname(target_link), os.path.basename(dist_location))
    shutil.move(dist_location, target_location)
    _safe_link(target_location, target_link)
    logger.debug('    installed {}'.format(target_location))
    return Package.from_href(target_location)

  def _purge_interpreter(self, interpreter_dir):
    try:
      logger.info('Detected stale interpreter `{}` in the interpreter cache, purging.'
                  .format(interpreter_dir))
      shutil.rmtree(interpreter_dir, ignore_errors=True)
    except Exception as e:
      logger.warn(
        'Caught exception {!r} during interpreter purge. Please run `./pants clean-all`!'
        .format(e)
      )
