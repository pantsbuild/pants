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

from functools import partial

from twitter.common.collections import maybe_list

from twitter.pants.base import manual, TargetDefinitionException

from .internal import InternalTarget
from .jar_dependency import JarDependency
from .jar_library import JarLibrary
from .jarable import Jarable
from .pants_target import Pants
from .with_sources import TargetWithSources


@manual.builddict(tags=["anylang", "thrift"])
class ThriftLibrary(InternalTarget, TargetWithSources, Jarable):
  """Defines a target that can be used to generate code from thrift IDL files."""

  def __init__(self, name, sources, dependencies=None, provides=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param provides: An optional :class:`twitter.pants.targets.Artifact` that describes how this
      thrift IDL library is published as a jar.
    """
    # TODO(John Sirois): Consider adding support for provides such that thrift-only IDL jar
    # publishing becomes an explicit choice pending inter-repo thrift-sharing idea shake-out.
    TargetWithSources.__init__(self, name, sources)
    InternalTarget.__init__(self, name,
                            maybe_list(dependencies or (),
                                       expected_type=(JarLibrary, Pants, ThriftJar, ThriftLibrary),
                                       raise_type=partial(TargetDefinitionException, self)))

    self._provides = provides
    self.is_codegen = True

  @property
  def provides(self):
    return self._provides

  def valid_dependency(self, dep):
    return isinstance(dep, (ThriftJar, ThriftLibrary))


@manual.builddict(tags=["anylang", "thrift"])
class ThriftJar(JarDependency):
  """Defines a jar that contains thrift IDL files that can be extracted and
  used to generate code.

  To ensure a consistent jar version across libraries, most repos wrap
  ThriftJar inside a :class:`twitter.pants.targets.jar_library.JarLibrary`
  in a a central location for 3rdparty library declarations. For example:

  ::

    jar_library(name='mybird-thrift',
      dependencies=[
        thrift_jar(org='com.twitter', name='mybird-thrift', rev='1.0.0')
      ]
    )
  """

  def __init__(self, org, name, rev=None, force=False, url=None, mutable=None, classifier='idl'):
    """
    :param string org: Equivalent to Maven groupId.
    :param string name: Equivalent to Maven artifactId.
    :param string rev: Equivalent to Maven version.
    :param boolean force: Force this version.
    :param string url: Artifact URL if using a non-standard repository layout.
    :param boolean mutable: If the artifact changes and should not be cached.
    :param string classifier: Equivalent to Maven classifier.
    """
    JarDependency.__init__(self, org, name, rev=rev, force=force, url=url, mutable=mutable)

    # TODO(John Sirois): abstract ivy specific configurations notion away
    self._configurations.append('idl')
    self.with_artifact(configuration='idl', classifier=classifier)
