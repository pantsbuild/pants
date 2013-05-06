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

from __future__ import print_function

__author__ = 'Brian Wickman'

from collections import defaultdict
import os
import sys

import pkg_resources

from twitter.common.collections import OrderedSet
from twitter.common.python.fetcher import Fetcher
from twitter.common.python.resolver import Resolver

from twitter.pants import is_concrete
from twitter.pants.base import Config
from twitter.pants.targets import (
  PythonBinary, PythonLibrary, PythonAntlrLibrary,
  PythonRequirement, PythonThriftLibrary, PythonTests)


def fetcher_from_config(config):
  return Fetcher(
    repositories = config.getlist('python-setup', 'repos', []),
    indices = config.getlist('python-setup', 'indices', []),
    external = config.getbool('python-setup', 'allow_pypi', True),
    download_cache = config.get('python-setup', 'cache', default=None))


class SilentResolver(Resolver):
  @classmethod
  def _log(cls, msg):
    if 'PANTS_VERBOSE' in os.environ:
      print('  Resolver: %s' % msg)


class PythonResolver(object):
  _VALID_DEPENDENCIES = {
    PythonLibrary: 'libraries',
    PythonRequirement: 'reqs',
    PythonBinary: 'binaries',
    PythonThriftLibrary: 'thrifts',
    PythonAntlrLibrary: 'antlrs',
    PythonTests: 'tests'
  }

  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  def __init__(self, targets):
    self._config = Config.load()
    self._targets = targets
    self._resolver = SilentResolver(
      caches = self._config.getlist('python-setup', 'local_eggs') +
                [self._config.get('python-setup', 'install_cache')],
      install_cache = self._config.get('python-setup', 'install_cache'),
      fetcher = fetcher_from_config(self._config))

  def debug(self, msg, indent=0):
    if 'PANTS_VERBOSE' in os.environ:
      print('%s%s' % (' ' * indent, msg))

  def resolve(self):
    children = defaultdict(OrderedSet)
    def add_dep(trg):
      if is_concrete(trg):
        for target_type, target_key in PythonResolver._VALID_DEPENDENCIES.items():
          if isinstance(trg, target_type):
            children[target_key].add(trg)
            return
      raise PythonResolver.InvalidDependencyException(trg)
    for target in self._targets:
      target.walk(add_dep)
    return children

  def dump(self):
    self.debug('Building PythonBinary %s:' % self._targets)

    targets = self.resolve()

    for lib in targets['libraries']:
      self.debug('Library: %s' % lib)

    for egg in targets['eggs']:
      self.debug('Egg: %s' % egg)

    reqs = OrderedSet([pkg_resources.Requirement.parse('distribute')]) | OrderedSet(
      req._requirement for req in targets['reqs'])
    for req in reqs:
      self.debug('Req: %s' % req)

    self.debug('Resolving...')
    dists = self._resolver.resolve(list(reqs))
    for dist in dists:
      self.debug('  => Dist: %s [%s]' % (dist, dist.location))

    for thr in targets['thrifts']:
      self.debug('Thrift: %s' % thr)

    for antlr in targets['antlrs']:
      self.debug('ANTLR: %s' % antlr)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    for binary in targets['binaries']:
      self.debug('Binary: %s' % binary)

    self.debug('Frozen.')
