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

import os

from twitter.common.dirutil import safe_mkdir
from twitter.common.python.distiller import Distiller
from twitter.common.python.http.link import SourceLink
from twitter.common.python.installer import Installer
from twitter.common.python.interpreter import PythonInterpreter, PythonIdentity
from twitter.common.python.obtainer import Obtainer

from .resolver import MultiResolver

from pkg_resources import Requirement


# TODO(wickman) Create a safer version of this and add to twitter.common.dirutil
def safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


class PythonInterpreterCache(object):
  def __init__(self, config, logger=None):
    self._path = config.get('python-setup', 'interpreter_cache')
    setuptools_req = 'setuptools==%s' % config.get('python-setup', 'setuptools_version')
    try:
      self._setuptools_requirement = Requirement.parse(setuptools_req, replacement=False)
    except TypeError:
      self._setuptools_requirement = Requirement.parse(setuptools_req)
    safe_mkdir(self._path)
    self._fetchers = MultiResolver.fetchers(config)
    self._crawler = MultiResolver.crawler(config)
    self._interpreters = set()
    self._logger = logger or (lambda msg: True)

  @property
  def interpreters(self):
    return self._interpreters

  @classmethod
  def interpreter_from_path(cls, path):
    interpreter_dir = os.path.basename(path)
    identity = PythonIdentity.from_path(interpreter_dir)
    try:
      executable = os.readlink(os.path.join(path, 'python'))
    except OSError:
      return None
    try:
      distribute_path = os.readlink(os.path.join(path, 'distribute'))
    except OSError:
      distribute_path = None
    return PythonInterpreter(executable, identity, distribute_path)

  def setup_distribute(self, interpreter, dest):
    obtainer = Obtainer(self._crawler, self._fetchers, [])
    obtainer_iterator = obtainer.iter(self._setuptools_requirement)
    links = [link for link in obtainer_iterator if isinstance(link, SourceLink)]
    for link in links:
      self._logger('Fetching %s' % link)
      sdist = link.fetch()
      self._logger('Installing %s' % sdist)
      installer = Installer(sdist, strict=False, interpreter=interpreter)
      dist = installer.distribution()
      self._logger('Distilling %s' % dist)
      egg = Distiller(dist).distill(into=dest)
      safe_link(egg, os.path.join(dest, 'distribute'))
      break

  def setup_interpreter(self, interpreter):
    interpreter_dir = os.path.join(self._path, str(interpreter.identity))
    safe_mkdir(interpreter_dir)
    safe_link(interpreter.binary, os.path.join(interpreter_dir, 'python'))
    if interpreter.distribute:
      safe_link(interpreter.distribute, os.path.join(interpreter_dir, 'distribute'))
    else:
      self.setup_distribute(interpreter, interpreter_dir)

  def setup_cached(self):
    for interpreter_dir in os.listdir(self._path):
      path = os.path.join(self._path, interpreter_dir)
      pi = self.interpreter_from_path(path)
      if pi:
        self._logger('Found interpreter %s: %s (cached)' % (pi.binary, str(pi.identity)))
        self._interpreters.add(pi)

  def setup_paths(self, paths):
    for interpreter in PythonInterpreter.all(paths):
      identity_str = str(interpreter.identity)
      path = os.path.join(self._path, identity_str)
      pi = self.interpreter_from_path(path)
      if pi is None or pi.distribute is None:
        self._logger('Found interpreter %s: %s (%s)' % (
            interpreter.binary,
            str(interpreter.identity),
            'uncached' if pi is None else 'incomplete'))
        self.setup_interpreter(interpreter)
        pi = self.interpreter_from_path(path)
        if pi is None or pi.distribute is None:
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
