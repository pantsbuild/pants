# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

from jvm_target import JvmTarget

from twitter.pants.base import Target, TargetDefinitionException

class JvmBinary(JvmTarget):
  """
    Defines a jvm binary consisting of a main class.  The binary can either collect the main class
    from an associated java source file or from its dependencies.
  """

  def __init__(self, name, main, source=None, dependencies=None, excludes=None):
    JvmTarget.__init__(self,
                       name=name,
                       sources=[source] if source else None,
                       dependencies=dependencies,
                       excludes=excludes)

    if not isinstance(main, basestring):
      raise TargetDefinitionException(self, 'main must be a fully qualified classname')

    if source and not isinstance(source, basestring):
      raise TargetDefinitionException(self, 'source must be a single relative file path')

    self.main = main


class IdentityMapper(object):
  """A mapper that maps files specified relative to a base directory."""

  def __init__(self, base):
    """The base directory files should be mapped from."""

    self.base = base

  def __call__(self, file):
    return os.path.join(self.base, file)

  def __repr__(self):
    return 'IdentityMapper(%s)' % self.base


class Bundle(object):
  """Defines a bundle of files mapped from their full path name to a path name in the bundle."""

  def __init__(self, mapper=None):
    """
      Creates a new bundle with an empty filemap.  If no mapper is specified, an IdentityMapper
      is used to map files into the bundle relative to the cwd.
    """

    self.mapper = mapper or IdentityMapper(os.getcwd())
    self.filemap = {}

  def add(self, *from_specs):
    self.filemap.update(((self.mapper(from_spec), from_spec) for from_spec in from_specs))
    return self

  def resolve(self):
    yield self

  def __repr__(self):
    return 'Bundle(%s, %s)' % (self.mapper, self.filemap)


class JvmApp(Target):
  """Defines a jvm app package consisting of a binary plus additional bundles of files."""

  def __init__(self, name, binary, bundles):
    Target.__init__(self, name, is_meta=False)

    if not binary:
      raise TargetDefinitionException(self, 'binary is required')

    binaries = list(binary.resolve())
    if len(binaries) != 1 or not isinstance(binaries[0], JvmBinary):
      raise TargetDefinitionException(self, 'must supply exactly 1 JvmBinary, got %s' % binary)
    self.binary = binaries[0]

    if not bundles:
      raise TargetDefinitionException(self, 'bundles must be specified')

    def is_resolvable(item):
      return hasattr(item, 'resolve')

    def is_bundle(bundle):
      return isinstance(bundle, Bundle)

    def resolve(item):
      return list(item.resolve()) if is_resolvable(item) else [None]

    if is_resolvable(bundles):
      bundles = resolve(bundles)

    self.bundles = []
    try:
      for item in iter(bundles):
        for bundle in resolve(item):
          if not is_bundle(bundle):
            raise TypeError()
          self.bundles.append(bundle)
    except TypeError:
      raise TargetDefinitionException(self, 'bundles must be one or more Bundle objects, '
                                            'got %s' % bundles)

  def _walk(self, walked, work, predicate=None):
    Target._walk(self, walked, work, predicate)
    self.binary._walk(walked, work, predicate)




