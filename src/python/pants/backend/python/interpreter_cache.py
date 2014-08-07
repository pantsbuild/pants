# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from pkg_resources import Requirement
import shutil


from pex.installer import EggInstaller
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.obtainer import Obtainer
from pex.package import EggPackage, SourcePackage

from pants.backend.python.python_setup import PythonSetup
from pants.backend.python.resolver import crawler_from_config, fetchers_from_config
from pants.util.dirutil import safe_mkdir


# TODO(wickman) Create a safer version of this and add to twitter.common.dirutil
def _safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


def _resolve_interpreter(config, interpreter, requirement, logger=print):
  """Given a :class:`PythonInterpreter` and :class:`Config`, and a requirement,
     return an interpreter with the capability of resolving that requirement or
    ``None`` if it's not possible to install a suitable requirement."""
  interpreter_cache = PythonInterpreterCache._cache_dir(config)
  interpreter_dir = os.path.join(interpreter_cache, str(interpreter.identity))
  if interpreter.satisfies([requirement]):
    return interpreter

  def installer_provider(sdist):
    return EggInstaller(sdist, strict=requirement.key != 'setuptools', interpreter=interpreter)

  egg = _resolve_and_link(
      config,
      requirement,
      os.path.join(interpreter_dir, requirement.key),
      installer_provider,
      logger=logger)
  if egg:
    return interpreter.with_extra(egg.name, egg.raw_version, egg.url)
  else:
    logger('Failed to resolve requirement %s for %s' % (requirement, interpreter))


def _resolve_and_link(config, requirement, target_link, installer_provider, logger=print):
  if os.path.exists(target_link) and os.path.exists(os.path.realpath(target_link)):
    egg = EggPackage(os.path.realpath(target_link))
    if egg.satisfies(requirement):
      return egg
  fetchers = fetchers_from_config(config)
  crawler = crawler_from_config(config)
  obtainer = Obtainer(crawler, fetchers, [])
  obtainer_iterator = obtainer.iter(requirement)
  links = [link for link in obtainer_iterator if isinstance(link, SourcePackage)]
  for link in links:
    logger('    fetching %s' % link.url)
    sdist = link.fetch()
    logger('    installing %s' % sdist)
    installer = installer_provider(sdist)
    dist_location = installer.bdist()
    target_location = os.path.join(os.path.dirname(target_link), os.path.basename(dist_location))
    shutil.move(dist_location, target_location)
    _safe_link(target_location, target_link)
    logger('    installed %s' % target_location)
    return EggPackage(target_location)


# This is a setuptools <1 and >1 compatible version of Requirement.parse.
# For setuptools <1, if you did Requirement.parse('setuptools'), it would
# return 'distribute' which of course is not desirable for us.  So they
# added a replacement=False keyword arg.  Sadly, they removed this keyword
# arg in setuptools >= 1 so we have to simply failover using TypeError as a
# catch for 'Invalid Keyword Argument'.
def _failsafe_parse(requirement):
  try:
    return Requirement.parse(requirement, replacement=False)
  except TypeError:
    return Requirement.parse(requirement)


def _resolve(config, interpreter, logger=print):
  """Resolve and cache an interpreter with a setuptools and wheel capability."""

  setuptools_requirement = _failsafe_parse(
      'setuptools==%s' % config.get('python-setup', 'setuptools_version', default='5.4.1'))
  wheel_requirement = _failsafe_parse(
      'wheel==%s' % config.get('python-setup', 'wheel_version', default='0.23.0'))

  interpreter = _resolve_interpreter(config, interpreter, setuptools_requirement, logger=logger)
  if interpreter:
    return _resolve_interpreter(config, interpreter, wheel_requirement, logger=logger)


class PythonInterpreterCache(object):
  @staticmethod
  def _cache_dir(config):
    return PythonSetup(config).scratch_dir('interpreter_cache', default_name='interpreters')

  @staticmethod
  def _matches(interpreter, filters):
    return any(interpreter.identity.matches(filt) for filt in filters)

  @classmethod
  def _matching(cls, interpreters, filters):
    for interpreter in interpreters:
      if cls._matches(interpreter, filters):
        yield interpreter

  @classmethod
  def select_interpreter(cls, compatibilities, allow_multiple=False):
    """Given a set of interpreters, either return them all if ``allow_multiple`` is ``True``;
    otherwise, return the lowest compatible interpreter.
    """
    if allow_multiple:
      return compatibilities
    return [min(compatibilities)] if compatibilities else []

  def __init__(self, config, logger=None):
    self._path = self._cache_dir(config)
    self._config = config
    safe_mkdir(self._path)
    self._interpreters = set()
    self._logger = logger or (lambda msg: True)

  @property
  def interpreters(self):
    """Returns the set of cached interpreters."""
    return self._interpreters

  def _interpreter_from_path(self, path, filters):
    interpreter_dir = os.path.basename(path)
    identity = PythonIdentity.from_path(interpreter_dir)
    try:
      executable = os.readlink(os.path.join(path, 'python'))
    except OSError:
      return None
    interpreter = PythonInterpreter(executable, identity)
    if self._matches(interpreter, filters):
      return _resolve(self._config, interpreter, logger=self._logger)
    return None

  def _setup_interpreter(self, interpreter):
    interpreter_dir = os.path.join(self._path, str(interpreter.identity))
    safe_mkdir(interpreter_dir)
    _safe_link(interpreter.binary, os.path.join(interpreter_dir, 'python'))
    return _resolve(self._config, interpreter, logger=self._logger)

  def _setup_cached(self, filters):
    for interpreter_dir in os.listdir(self._path):
      path = os.path.join(self._path, interpreter_dir)
      pi = self._interpreter_from_path(path, filters)
      if pi:
        self._logger('Detected interpreter %s: %s' % (pi.binary, str(pi.identity)))
        self._interpreters.add(pi)

  def _setup_paths(self, paths, filters):
    for interpreter in self._matching(PythonInterpreter.all(paths), filters):
      identity_str = str(interpreter.identity)
      path = os.path.join(self._path, identity_str)
      pi = self._interpreter_from_path(path, filters)
      if pi is None:
        self._setup_interpreter(interpreter)
        pi = self._interpreter_from_path(path, filters)
        if pi is None:
          continue
      self._interpreters.add(pi)

  def matches(self, filters):
    """Given some filters, yield any interpreter that matches at least one of them.

    :param filters: A sequence of strings that constrain the interpreter compatibility for this
      cache, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
      for requirements agnostic to interpreter class.
    """
    for match in self._matching(self._interpreters, filters):
      yield match

  def setup(self, paths=(), force=False, filters=(b'',)):
    """Sets up a cache of python interpreters.

    NB: Must be called prior to accessing the ``interpreters`` property or the ``matches`` method.

    :param paths: The paths to search for a python interpreter; the system ``PATH`` by default.
    :param bool force: When ``True`` the interpreter cache is always re-built.
    :param filters: A sequence of strings that constrain the interpreter compatibility for this
      cache, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
      for requirements agnostic to interpreter class.
    """
    has_setup = False
    setup_paths = paths or os.getenv('PATH').split(os.pathsep)
    self._setup_cached(filters)
    if force:
      has_setup = True
      self._setup_paths(setup_paths, filters)
    matches = list(self.matches(filters))
    if len(matches) == 0 and not has_setup:
      self._setup_paths(setup_paths, filters)
      matches = list(self.matches(filters))
    if len(matches) == 0:
      self._logger('Found no valid interpreters!')
    return matches
