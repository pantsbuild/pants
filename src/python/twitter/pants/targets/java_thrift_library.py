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

from twitter.pants.base import TargetDefinitionException

from .exportable_jvm_library import ExportableJvmLibrary


class JavaThriftLibrary(ExportableJvmLibrary):
  """Defines a target that builds java or scala stubs from a thrift IDL file."""

  _COMPILERS = frozenset(['thrift', 'scrooge', 'scrooge-legacy'])
  _COMPILER_DEFAULT = 'thrift'

  _LANGUAGES = frozenset(['java', 'scala'])
  _LANGUAGE_DEFAULT = 'java'

  _RPC_STYLES = frozenset(['sync', 'finagle', 'ostrich'])
  _RPC_STYLE_DEFAULT = 'sync'

  def __init__(self, name, sources, provides=None, dependencies=None, excludes=None,
               compiler=_COMPILER_DEFAULT, language=_LANGUAGE_DEFAULT, rpc_style=_RPC_STYLE_DEFAULT,
               namespace_map=None, buildflags=None, exclusives=None):
    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the thrift source files this module's jar is compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    compiler: An optional compiler used to compile the thrift files {'thrift', 'scrooge',
                                                                               'scrooge-legacy'}.
        Defaults to 'thrift'.
    language: An optional language used to generate the output files {'java', 'scala'}.
        Defaults to 'java'.
    rpc_style: An optional rpc style in code generation {'sync', 'finagle', 'ostrich'}.
        Defaults to 'sync'.
    namespace_map: A dictionary of namespaces to remap (old: new)
    buildflags: DEPRECATED - A list of additional command line arguments to pass to the underlying
        build system for this target - now ignored.
    exclusives:   An optional map of exclusives tags. See CheckExclusives for details.
    """
    ExportableJvmLibrary.__init__(self, name, sources, provides, dependencies, excludes,
                                  exclusives=exclusives)
    self.add_labels('codegen', 'java')

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

  def _as_jar_dependency(self):
    return ExportableJvmLibrary._as_jar_dependency(self).with_sources()
