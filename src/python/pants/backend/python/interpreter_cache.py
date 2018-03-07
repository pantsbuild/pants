# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.package import EggPackage, Package, SourcePackage
from pex.resolver import resolve
from pex.variables import Variables

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TaskError
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir
from pants.util.memo import memoized_property


# TODO(wickman) Create a safer version of this and add to twitter.common.dirutil
def _safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


class PythonInterpreterCache(object):

  class UnsatisfiableInterpreterConstraintsError(TaskError):
    """Indicates a python interpreter matching given constraints could not be located."""

  @staticmethod
  def _matches(interpreter, filters):
    return any(interpreter.identity.matches(filt) for filt in filters)

  @classmethod
  def _matching(cls, interpreters, filters):
    for interpreter in interpreters:
      if cls._matches(interpreter, filters):
        yield interpreter

  @classmethod
  def pex_python_paths(cls):
    """A list of paths to Python interpreter binaries as defined by a
    PEX_PYTHON_PATH defined in either in '/etc/pexrc', '~/.pexrc'.
    PEX_PYTHON_PATH defines a colon-seperated list of paths to interpreters
    that a pex can be built and ran against.

    :return: paths to interpreters as specified by PEX_PYTHON_PATH
    :rtype: list
    """
    ppp = Variables.from_rc().get('PEX_PYTHON_PATH')
    if ppp:
      return ppp.split(os.pathsep)
    else:
      return []

  def __init__(self, python_setup, python_repos, logger=None):
    self._python_setup = python_setup
    self._python_repos = python_repos
    self._logger = logger or (lambda msg: True)

  @memoized_property
  def _cache_dir(self):
    cache_dir = self._python_setup.interpreter_cache_dir
    safe_mkdir(cache_dir)
    return cache_dir

  def select_interpreter_for_targets(self, targets):
    """Pick an interpreter compatible with all the specified targets."""
    tgts_with_compatibilities = []
    filters = set()
    for target in targets:
      if isinstance(target, PythonTarget) and target.compatibility:
        tgts_with_compatibilities.append(target)
        filters.update(target.compatibility)

    allowed_interpreters = set(self.setup(filters=filters))

    # Constrain allowed_interpreters based on each target's compatibility requirements.
    for target in tgts_with_compatibilities:
      compatible_with_target = set(self._matching(allowed_interpreters, target.compatibility))
      allowed_interpreters &= compatible_with_target

    if not allowed_interpreters:
      # Create a helpful error message.
      unique_compatibilities = set(tuple(t.compatibility) for t in tgts_with_compatibilities)
      unique_compatibilities_strs = [','.join(x) for x in unique_compatibilities if x]
      tgts_with_compatibilities_strs = [t.address.spec for t in tgts_with_compatibilities]
      raise self.UnsatisfiableInterpreterConstraintsError(
        'Unable to detect a suitable interpreter for compatibilities: {} '
        '(Conflicting targets: {})'.format(' && '.join(unique_compatibilities_strs),
                                           ', '.join(tgts_with_compatibilities_strs)))
    # Return the lowest compatible interpreter.
    return min(allowed_interpreters)

  def _interpreter_from_path(self, path, filters):
    interpreter_dir = os.path.basename(path)
    identity = PythonIdentity.from_path(interpreter_dir)
    try:
      executable = os.readlink(os.path.join(path, 'python'))
    except OSError:
      return None
    interpreter = PythonInterpreter(executable, identity)
    if self._matches(interpreter, filters):
      return self._resolve(interpreter)
    return None

  def _setup_interpreter(self, interpreter, cache_target_path):
    with safe_concurrent_creation(cache_target_path) as safe_path:
      os.mkdir(safe_path)  # Parent will already have been created by safe_concurrent_creation.
      os.symlink(interpreter.binary, os.path.join(safe_path, 'python'))
      return self._resolve(interpreter, safe_path)

  def _setup_cached(self, filters):
    """Find all currently-cached interpreters."""
    for interpreter_dir in os.listdir(self._cache_dir):
      if os.path.isdir(interpreter_dir):
        path = os.path.join(self._cache_dir, interpreter_dir)
        pi = self._interpreter_from_path(path, filters)
        if pi:
          self._logger('Detected interpreter {}: {}'.format(pi.binary, str(pi.identity)))
          yield pi

  def _setup_paths(self, paths, filters):
    """Find interpreters under paths, and cache them."""
    for interpreter in self._matching(PythonInterpreter.all(paths), filters):
      identity_str = str(interpreter.identity)
      cache_path = os.path.join(self._cache_dir, identity_str)
      pi = self._interpreter_from_path(cache_path, filters)
      if pi is None:
        self._setup_interpreter(interpreter, cache_path)
        pi = self._interpreter_from_path(cache_path, filters)
      if pi:
        yield pi

  def setup(self, paths=(), filters=(b'',)):
    """Sets up a cache of python interpreters.

    :param paths: The paths to search for a python interpreter; the system ``PATH`` by default.
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
    setup_paths = (paths
                   or self.pex_python_paths()
                   or self._python_setup.interpreter_search_paths
                   or os.getenv('PATH').split(os.pathsep))

    def unsatisfied_filters(interpreters):
      return filter(lambda f: len(list(self._matching(interpreters, [f]))) == 0, filters)

    interpreters = []
    with OwnerPrintingInterProcessFileLock(path=os.path.join(self._cache_dir, '.file_lock')):
      interpreters.extend(self._setup_cached(filters))
      if unsatisfied_filters(interpreters):
        interpreters.extend(self._setup_paths(setup_paths, filters))

    for filt in unsatisfied_filters(interpreters):
      self._logger('No valid interpreters found for {}!'.format(filt))

    matches = list(self._matching(interpreters, filters))
    if len(matches) == 0:
      self._logger('Found no valid interpreters!')

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
      self._logger('Failed to resolve requirement {} for {}'.format(requirement, interpreter))

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
    distributions = resolve(requirements=[requirement],
                            fetchers=self._python_repos.get_fetchers(),
                            interpreter=interpreter,
                            context=self._python_repos.get_network_context(),
                            precedence=precedence)
    if not distributions:
      return None

    assert len(distributions) == 1, ('Expected exactly 1 distribution to be resolved for {}, '
                                     'found:\n\t{}'.format(requirement,
                                                           '\n\t'.join(map(str, distributions))))

    dist_location = distributions[0].location
    target_location = os.path.join(os.path.dirname(target_link), os.path.basename(dist_location))
    shutil.move(dist_location, target_location)
    _safe_link(target_location, target_link)
    self._logger('    installed {}'.format(target_location))
    return Package.from_href(target_location)
