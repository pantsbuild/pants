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

from twitter.pants.base import manual

from .exportable_jvm_library import ExportableJvmLibrary


@manual.builddict(tags=["jvm"])
class JavaAntlrLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from Antlr grammar files."""

  def __init__(self,
               name,
               sources,
               provides=None,
               dependencies=None,
               excludes=None,
               compiler='antlr3'):

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
    :param compiler: The name of the compiler used to compile the ANTLR files.
        Currently only supports 'antlr3' and 'antlr4'
    """

    ExportableJvmLibrary.__init__(self,
                                  name,
                                  sources,
                                  provides,
                                  dependencies,
                                  excludes)
    self.add_labels('codegen')

    if compiler not in ('antlr3', 'antlr4'):
        raise ValueError("Illegal value for 'compiler': {}".format(compiler))
    self.compiler = compiler
