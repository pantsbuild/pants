# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

from __future__ import print_function

import os

from twitter.common.dirutil import safe_mkdir
from twitter.common.python.http.link import SourceLink
from twitter.common.python.http.link import EggLink
from twitter.common.python.installer import EggInstaller
from twitter.common.python.interpreter import (
    PythonCapability,
    PythonIdentity,
    PythonInterpreter,
)
from twitter.common.python.obtainer import Obtainer

from .python_setup import PythonSetup
from .resolver import crawler_from_config, fetchers_from_config

from pkg_resources import Requirement


# TODO(wickman) Create a safer version of this and add to twitter.common.dirutil
def safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


def resolve_interpreter(config, interpreter, requirement, logger=print):
  """Given a :class:`PythonInterpreter` and :class:`Config`, and a requirement,
     return an interpreter with the capability of resolving that requirement or
     None if it's not possible to install a suitable requirement."""
  interpreter_cache = PythonInterpreterCache.cache_dir(config)
  interpreter_dir = os.path.join(interpreter_cache, str(interpreter.identity))
  if interpreter.satisfies(PythonCapability([requirement])):
    return interpreter
  def installer_provider(sdist):
    return EggInstaller(sdist, strict=requirement.key != 'setuptools', interpreter=interpreter)
  egg = resolve_and_link(
      config,
      requirement,
      os.path.join(interpreter_dir, requirement.key),
      installer_provider,
      logger=logger)
  if egg:
    return interpreter.with_extra(egg.name, egg.raw_version, egg.url)
  else:
    logger('Failed to resolve requirement %s for %s' % (requirement, interpreter))


def resolve_and_link(config, requirement, target_link, installer_provider, logger=print):
  if os.path.exists(target_link) and os.path.exists(os.path.realpath(target_link)):
    egg = EggLink(os.path.realpath(target_link))
    if egg.satisfies(requirement):
      return egg
  fetchers = fetchers_from_config(config)
  crawler = crawler_from_config(config)
  obtainer = Obtainer(crawler, fetchers, [])
  obtainer_iterator = obtainer.iter(requirement)
  links = [link for link in obtainer_iterator if isinstance(link, SourceLink)]
  for link in links:
    logger('    fetching %s' % link.url)
    sdist = link.fetch()
    logger('    installing %s' % sdist)
    installer = installer_provider(sdist)
    dist_location = installer.bdist()
    target_location = os.path.join(os.path.dirname(target_link), os.path.basename(dist_location))
    os.rename(dist_location, target_location)
    safe_link(target_location, target_link)
    logger('    installed %s' % target_location)
    return EggLink(target_location)


# This is a setuptools <1 and >1 compatible version of Requirement.parse.
# For setuptools <1, if you did Requirement.parse('setuptools'), it would
# return 'distribute' which of course is not desirable for us.  So they
# added a replacement=False keyword arg.  Sadly, they removed this keyword
# arg in setuptools >= 1 so we have to simply failover using TypeError as a
# catch for 'Invalid Keyword Argument'.
def failsafe_parse(requirement):
  try:
    return Requirement.parse(requirement, replacement=False)
  except TypeError:
    return Requirement.parse(requirement)


def resolve(config, interpreter, logger=print):
  """Resolve and cache an interpreter with a setuptools and wheel capability."""

  setuptools_requirement = failsafe_parse(
      'setuptools==%s' % config.getdefault('python-setup', 'setuptools_version', '2.2'))
  wheel_requirement = failsafe_parse(
      'wheel==%s' % config.getdefault('python-setup', 'wheel_version', '0.22.0'))

  interpreter = resolve_interpreter(config, interpreter, setuptools_requirement, logger=logger)
  if interpreter:
    return resolve_interpreter(config, interpreter, wheel_requirement, logger=logger)


class PythonInterpreterCache(object):
  @staticmethod
  def cache_dir(config):
    return PythonSetup(config).scratch_dir('interpreter_cache', default_name='interpreters')

  def __init__(self, config, logger=None):
    self._path = self.cache_dir(config)
    self._config = config
    safe_mkdir(self._path)
    self._interpreters = set()
    self._logger = logger or (lambda msg: True)

  @property
  def interpreters(self):
    return self._interpreters

  def interpreter_from_path(self, path):
    interpreter_dir = os.path.basename(path)
    identity = PythonIdentity.from_path(interpreter_dir)
    try:
      executable = os.readlink(os.path.join(path, 'python'))
    except OSError:
      return None
    interpreter = PythonInterpreter(executable, identity)
    return resolve(self._config, interpreter, logger=self._logger)

  def setup_interpreter(self, interpreter):
    interpreter_dir = os.path.join(self._path, str(interpreter.identity))
    safe_mkdir(interpreter_dir)
    safe_link(interpreter.binary, os.path.join(interpreter_dir, 'python'))
    return resolve(self._config, interpreter)

  def setup_cached(self):
    for interpreter_dir in os.listdir(self._path):
      path = os.path.join(self._path, interpreter_dir)
      pi = self.interpreter_from_path(path)
      if pi:
        self._logger('Detected interpreter %s: %s' % (pi.binary, str(pi.identity)))
        self._interpreters.add(pi)

  def setup_paths(self, paths):
    for interpreter in PythonInterpreter.all(paths):
      identity_str = str(interpreter.identity)
      path = os.path.join(self._path, identity_str)
      pi = self.interpreter_from_path(path)
      if pi is None:
        self.setup_interpreter(interpreter)
        pi = self.interpreter_from_path(path)
        if pi is None:
          continue
      self._interpreters.add(pi)

  def matches(self, filters):
    for interpreter in self._interpreters:
      if any(interpreter.identity.matches(filt) for filt in filters):
        yield interpreter

  def setup(self, paths=(), force=False, filters=('',)):
    has_setup = False
    setup_paths = paths or os.getenv('PATH').split(os.pathsep)
    self.setup_cached()
    if force:
      has_setup = True
      self.setup_paths(setup_paths)
    matches = list(self.matches(filters))
    if len(matches) == 0 and not has_setup:
      self.setup_paths(setup_paths)
      matches = list(self.matches(filters))
    if len(matches) == 0:
      self._logger('Found no valid interpreters!')
    return matches

  def select_interpreter(self, compatibilities, allow_multiple=False):
    if allow_multiple:
      return compatibilities
    me = PythonInterpreter.get()
    if me in compatibilities:
      return [me]
    return [min(compatibilities)] if compatibilities else []
