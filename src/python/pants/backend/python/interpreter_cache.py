# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pex.archiver import Archiver
from pex.crawler import Crawler
from pex.installer import EggInstaller
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.iterator import Iterator
from pex.package import EggPackage, SourcePackage

from pants.util.dirutil import safe_mkdir


# TODO(wickman) Create a safer version of this and add to twitter.common.dirutil
def _safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


class PythonInterpreterCache(object):
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

  def __init__(self, python_setup, python_repos, logger=None):
    self._python_setup = python_setup
    self._python_repos = python_repos
    self._cache_dir = os.path.join(python_setup.scratch_dir, 'interpreters')
    safe_mkdir(self._cache_dir)
    self._interpreters = set()
    self._logger = logger or (lambda msg: True)
    self._default_filters = (python_setup.interpreter_requirement or b'',)

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
      return self._resolve(interpreter)
    return None

  def _setup_interpreter(self, interpreter, cache_path):
    safe_mkdir(cache_path)
    _safe_link(interpreter.binary, os.path.join(cache_path, 'python'))
    return self._resolve(interpreter)

  def _setup_cached(self, filters):
    for interpreter_dir in os.listdir(self._cache_dir):
      path = os.path.join(self._cache_dir, interpreter_dir)
      pi = self._interpreter_from_path(path, filters)
      if pi:
        self._logger('Detected interpreter {}: {}'.format(pi.binary, str(pi.identity)))
        self._interpreters.add(pi)

  def _setup_paths(self, paths, filters):
    for interpreter in self._matching(PythonInterpreter.all(paths), filters):
      identity_str = str(interpreter.identity)
      cache_path = os.path.join(self._cache_dir, identity_str)
      pi = self._interpreter_from_path(cache_path, filters)
      if pi is None:
        self._setup_interpreter(interpreter, cache_path)
        pi = self._interpreter_from_path(cache_path, filters)
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
    filters = self._default_filters if not any(filters) else filters
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

  def _resolve(self, interpreter):
    """Resolve and cache an interpreter with a setuptools and wheel capability."""
    interpreter = self._resolve_interpreter(interpreter,
                                            self._python_setup.setuptools_requirement())
    if interpreter:
      return self._resolve_interpreter(interpreter, self._python_setup.wheel_requirement())


  def _resolve_interpreter(self, interpreter, requirement):
    """Given a :class:`PythonInterpreter` and a requirement, return an interpreter with the
    capability of resolving that requirement or ``None`` if it's not possible to install a
    suitable requirement.
    """
    interpreter_dir = os.path.join(self._cache_dir, str(interpreter.identity))
    if interpreter.satisfies([requirement]):
      return interpreter

    def installer_provider(sdist):
      return EggInstaller(
        Archiver.unpack(sdist),
        strict=requirement.key != 'setuptools',
        interpreter=interpreter)

    egg = self._resolve_and_link(
      requirement,
      os.path.join(interpreter_dir, requirement.key),
      installer_provider)

    if egg:
      return interpreter.with_extra(egg.name, egg.raw_version, egg.path)
    else:
      self._logger('Failed to resolve requirement {} for {}'.format(requirement, interpreter))

  def _resolve_and_link(self, requirement, target_link, installer_provider):
    # Short-circuit if there is a local copy.
    if os.path.exists(target_link) and os.path.exists(os.path.realpath(target_link)):
      egg = EggPackage(os.path.realpath(target_link))
      if egg.satisfies(requirement):
        return egg

    fetchers = self._python_repos.get_fetchers()
    context = self._python_repos.get_network_context()
    iterator = Iterator(fetchers=fetchers, crawler=Crawler(context))
    links = [link for link in iterator.iter(requirement) if isinstance(link, SourcePackage)]

    for link in links:
      self._logger('    fetching {}'.format(link.url))
      sdist = context.fetch(link)
      self._logger('    installing {}'.format(sdist))
      installer = installer_provider(sdist)
      dist_location = installer.bdist()
      target_location = os.path.join(os.path.dirname(target_link), os.path.basename(dist_location))
      shutil.move(dist_location, target_location)
      _safe_link(target_location, target_link)
      self._logger('    installed {}'.format(target_location))
      return EggPackage(target_location)
