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

__author__ = 'Brian Larson'

from twitter.pants.targets.exportable_jvm_library import ExportableJvmLibrary


class JavaAntlrLibrary(ExportableJvmLibrary):
  """Defines a target that builds java stubs from an Antlr grammar file."""

  def __init__(self,
               name,
               sources,
               provides = None,
               dependencies = None,
               excludes = None,
               compiler = 'antlr3'):

    """name: The name of this module target, addressable via pants via the portion of the spec
        following the colon
    sources: A list of paths containing the Antlr source files this module's jar is compiled from
    provides: An optional Dependency object indicating the The ivy artifact to export
    dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies of
        this module.
    excludes: An optional list of dependency exclude patterns to filter all of this module's
        transitive dependencies against.
    compiler: The name of the compiler used to compile the ANTLR files.
        Currently only supports 'antlr3' and 'antlr4'"""

    ExportableJvmLibrary.__init__(self,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes)
    self.add_labels('codegen', 'java')

    if compiler not in ['antlr3', 'antlr4']:
        raise ValueError("Illegal value for 'compiler': {}".format(compiler))
    self.compiler = compiler

  def _as_jar_dependency(self):
    return ExportableJvmLibrary._as_jar_dependency(self).with_sources()
