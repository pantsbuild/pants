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

from functools import partial

from twitter.common.collections import maybe_list
from twitter.common.dirutil import Fileset
from twitter.common.lang import Compatibility

from twitter.pants.base import manual, ParseContext
from twitter.pants.base.target import TargetDefinitionException
from twitter.pants.targets import JarLibrary, util

from .internal import InternalTarget
from .jvm_target import JvmTarget
from .pants_target import Pants
from .resources import WithResources


@manual.builddict(tags=["jvm"])
class JvmBinary(JvmTarget, WithResources):
  """Produces a JVM binary optionally identifying a launcher main class.

  Below are a summary of how key goals affect targets of this type:

  * ``bundle`` - Creates a self-contained directory with the binary and all
    its dependencies, optionally archived, suitable for deployment.
  * ``binary`` - Create an executable jar of the binary. On the JVM
    this means the jar has a manifest specifying the main class.
  * ``run`` - Executes the main class of this binary locally.
  """
  def __init__(self, name,
               main=None,
               basename=None,
               source=None,
               resources=None,
               dependencies=None,
               excludes=None,
               deploy_excludes=None,
               configurations=None,
               exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param string main: The name of the ``main`` class, e.g.,
      ``'com.twitter.common.examples.pingpong.Main'``. This class may be
      present as the source of this target or depended-upon library.
    :param string basename: Base name for the generated ``.jar`` file, e.g.,
      ``'pingpong'``. (By default, uses ``name`` param)
    :param string source: Name of one ``.java`` or ``.scala`` file (a good
      place for a ``main``).
    :param resources: List of ``resource``\s to include in bundle.
    :param dependencies: List of targets (probably ``java_library`` and
     ``scala_library`` targets) to "link" in.
    :param excludes: List of ``exclude``\s to filter this target's transitive
     dependencies against.
    :param deploy_excludes: List of ``excludes`` to apply at deploy time.
      If you, for example, deploy a java servlet that has one version of
      ``servlet.jar`` onto a Tomcat environment that provides another version,
      they might conflict. ``deploy_excludes`` gives you a way to build your
      code but exclude the conflicting ``jar`` when deploying.
    :param configurations: Ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """
    super(JvmBinary, self).__init__(name=name,
                                    sources=[source] if source else None,
                                    dependencies=dependencies,
                                    excludes=excludes,
                                    configurations=configurations,
                                    exclusives=exclusives)

    if main and not isinstance(main, Compatibility.string):
      raise TargetDefinitionException(self, 'main must be a fully qualified classname')

    if source and not isinstance(source, Compatibility.string):
      raise TargetDefinitionException(self, 'source must be a single relative file path')

    self.main = main
    self.basename = basename or name
    self.resources = resources
    self.deploy_excludes = deploy_excludes or []


class RelativeToMapper(object):
  """A mapper that maps files specified relative to a base directory."""

  def __init__(self, base):
    """The base directory files should be mapped from."""

    self.base = base

  def __call__(self, file):
    return os.path.relpath(file, self.base)

  def __repr__(self):
    return 'IdentityMapper(%s)' % self.base


@manual.builddict(tags=["jvm"])
class Bundle(object):
  """A set of files to include in an application bundle.

  Looking for Java-style resources accessible via the ``Class.getResource`` API?
  Those are :ref:`bdict_resources`\ .

  Files added to the bundle will be included when bundling an application target.
  By default relative paths are preserved. For example, to include ``config``
  and ``scripts`` directories: ::

    bundles=[
      bundle().add(rglobs('config/*', 'scripts/*')),
    ]

  To include files relative to some path component use the ``relative_to`` parameter.
  The following places the contents of ``common/config`` in a  ``config`` directory
  in the bundle. ::

    bundles=[
      bundle(relative_to='common').add(globs('common/config/*'))
    ]
  """

  def __init__(self, base=None, mapper=None, relative_to=None):
    """
    :param mapper: Function that takes a path string and returns a path string. Takes a path in
      the source tree, returns a path to use in the resulting bundle. By default, an identity
      mapper.
    :param string relative_to: Set up a simple mapping from source path to bundle path.
      E.g., ``relative_to='common'`` removes that prefix from all files in the application bundle.
    """
    if mapper and relative_to:
      raise ValueError("Must specify exactly one of 'mapper' or 'relative_to'")

    if relative_to:
      base = base or ParseContext.path(relative_to)
      if not os.path.isdir(base):
        raise ValueError('Could not find a directory to bundle relative to at %s' % base)
      self.mapper = RelativeToMapper(base)
    else:
      self.mapper = mapper or RelativeToMapper(base or ParseContext.path())

    self.filemap = {}

  @manual.builddict()
  def add(self, *filesets):
    """Add files to the bundle, where ``filesets`` is a filename, ``globs``, or ``rglobs``.
    Note this is a variable length param and may be specified any number of times.
    """
    for fileset in filesets:
      paths = fileset() if isinstance(fileset, Fileset) \
                        else fileset if hasattr(fileset, '__iter__') \
                        else [fileset]
      self.filemap.update(((os.path.abspath(path), self.mapper(path)) for path in paths))
    return self

  def resolve(self):
    yield self

  def __repr__(self):
    return 'Bundle(%s, %s)' % (self.mapper, self.filemap)


@manual.builddict(tags=["jvm"])
class JvmApp(InternalTarget):
  """A JVM-based application consisting of a binary plus "extra files".

  Invoking the ``bundle`` goal on one of these targets creates a
  self-contained artifact suitable for deployment on some other machine.
  The artifact contains the executable jar, its dependencies, and
  extra files like config files, startup scripts, etc.
  """

  def __init__(self, name, binary, bundles, basename=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param binary: The :class:`twitter.pants.targets.jvm_binary.JvmBinary`,
      or a :class:`twitter.pants.targets.pants_target.Pants` pointer to one.
    :param bundles: One or more :class:`twitter.pants.targets.jvm_binary.Bundle`'s
      describing "extra files" that should be included with this app
      (e.g.: config files, startup scripts).
    :param string basename: Name of this application, if different from the
      ``name``. Pants uses this in the ``bundle`` goal to name the distribution
      artifact. In most cases this parameter is not necessary.
    """
    super(JvmApp, self).__init__(name, dependencies=[])

    self._binaries = maybe_list(
        util.resolve(binary),
        expected_type=(Pants, JarLibrary, JvmBinary),
        raise_type=partial(TargetDefinitionException, self))

    self._bundles = maybe_list(bundles, expected_type=Bundle,
                               raise_type=partial(TargetDefinitionException, self))

    if name == basename:
      raise TargetDefinitionException(self, 'basename must not equal name.')
    self.basename = basename or name

    self._resolved_binary = None
    self._resolved_bundles = []

  def is_jvm_app(self):
    return True

  @property
  def binary(self):
    self._maybe_resolve_binary()
    return self._resolved_binary

  def _maybe_resolve_binary(self):
    if self._binaries is not None:
      binaries_list = []
      for binary in self._binaries:
        binaries_list.extend(filter(lambda t: t.is_concrete, binary.resolve()))

      if len(binaries_list) != 1 or not isinstance(binaries_list[0], JvmBinary):
        raise TargetDefinitionException(self,
                                        'must supply exactly 1 JvmBinary, got %s' % binaries_list)
      self._resolved_binary = binaries_list[0]
      self.update_dependencies([self._resolved_binary])
      self._binaries = None

  @property
  def bundles(self):
    self._maybe_resolve_bundles()
    return self._resolved_bundles

  def _maybe_resolve_bundles(self):
    if self._bundles is not None:
      def is_resolvable(item):
        return hasattr(item, 'resolve')

      def is_bundle(bundle):
        return isinstance(bundle, Bundle)

      def resolve(item):
        return list(item.resolve()) if is_resolvable(item) else [None]

      if is_resolvable(self._bundles):
        self._bundles = resolve(self._bundles)

      try:
        for item in iter(self._bundles):
          for bundle in resolve(item):
            if not is_bundle(bundle):
              raise TypeError()
            self._resolved_bundles.append(bundle)
      except TypeError:
        raise TargetDefinitionException(self, 'bundles must be one or more Bundle objects, '
                                              'got %s' % self._bundles)
      self._bundles = None

  @property
  def dependencies(self):
    self._maybe_resolve_binary()
    return super(JvmApp, self).dependencies

  def resolve(self):
    # TODO(John Sirois): Clean this up when BUILD parse refactoring is tackled.
    unused_resolved_binary = self.binary
    unused_resolved_bundles = self.bundles

    for resolved in super(JvmApp, self).resolve():
      yield resolved
