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

from collections import Iterable
from functools import partial

from twitter.common.collections import maybe_list

from twitter.pants.base import manual, TargetDefinitionException

from .jar_dependency import JarDependency
from .jvm_target import JvmTarget
from .pants_target import Pants


@manual.builddict(tags=['java'])
class JavaThriftLibrary(JvmTarget):
  """Generates a stub Java or Scala library from thrift IDL files."""


  _COMPILERS = frozenset(['thrift', 'scrooge', 'scrooge-legacy'])
  _COMPILER_DEFAULT = 'thrift'

  _LANGUAGES = frozenset(['java', 'scala'])
  _LANGUAGE_DEFAULT = 'java'

  _RPC_STYLES = frozenset(['sync', 'finagle', 'ostrich'])
  _RPC_STYLE_DEFAULT = 'sync'

  def __init__(self,
               name,
               sources,
               provides=None,
               dependencies=None,
               excludes=None,
               compiler=_COMPILER_DEFAULT,
               language=_LANGUAGE_DEFAULT,
               rpc_style=_RPC_STYLE_DEFAULT,
               namespace_map=None,
               exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param Artifact provides:
      The :class:`twitter.pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param compiler: An optional compiler used to compile the thrift files.
    :param language: The language used to generate the output files.
      One of 'java' or 'scala' with a default of 'java'.
    :param rpc_style: An optional rpc style to generate service stubs with.
      One of 'sync', 'finagle' or 'ostrich' with a default of 'sync'.
    :param namespace_map: A dictionary of namespaces to remap (old: new)
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """

    # It's critical that provides is set 1st since _provides() is called elsewhere in the
    # constructor flow.
    self._provides = provides

    super(JavaThriftLibrary, self).__init__(
        name,
        sources,
        dependencies,
        excludes,
        exclusives=exclusives)

    self.add_labels('codegen')

    # 'java' shouldn't be here, but is currently required to prevent lots of chunking islands.
    # See comment in goal.py for details.
    self.add_labels('java')

    if dependencies:
      if not isinstance(dependencies, Iterable):
        raise TargetDefinitionException(self,
                                        'dependencies must be Iterable but was: %s' % dependencies)
      maybe_list(dependencies, expected_type=(JarDependency, JavaThriftLibrary, Pants),
                 raise_type=partial(TargetDefinitionException, self))

    def check_value_for_arg(arg, value, values):
      if value not in values:
        raise TargetDefinitionException(self, "%s may only be set to %s ('%s' not valid)" %
                                        (arg, ', or '.join(map(repr, values)), value))
      return value

    # TODO(John Sirois): The defaults should be grabbed from the workspace config.

    # some gen BUILD files explicitly set this to None
    compiler = compiler or self._COMPILER_DEFAULT
    self.compiler = check_value_for_arg('compiler', compiler, self._COMPILERS)

    language = language or self._LANGUAGE_DEFAULT
    self.language = check_value_for_arg('language', language, self._LANGUAGES)

    rpc_style = rpc_style or self._RPC_STYLE_DEFAULT
    self.rpc_style = check_value_for_arg('rpc_style', rpc_style, self._RPC_STYLES)

    self.namespace_map = namespace_map

  @property
  def is_thrift(self):
    return True

  @property
  def provides(self):
    return self._provides
