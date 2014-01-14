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

from twitter.common.collections import OrderedSet
from twitter.pants.targets.python_target import PythonTarget
from twitter.pants.targets.pants_target import Pants

class PythonAntlrLibrary(PythonTarget):
  """Generates a stub Python library from Antlr grammar files."""

  def __init__(self, name, module,
               antlr_version = '3.1.3',
               sources = None,
               resources = None,
               dependencies = None,
               exclusives=None):
    """
    :param name: Name of library
    :param module: everything beneath module is relative to this module name, None if root namespace
    :param antlr_version:
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
        recommended that your application uses the pkgutil package to access these
        resources in a .zip-module friendly way.)
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """

    def get_all_deps():
      all_deps = OrderedSet()
      all_deps.update(Pants('3rdparty/python:antlr-%s' % antlr_version).resolve())
      if dependencies:
        all_deps.update(dependencies)
      return all_deps

    PythonTarget.__init__(self, name, sources, resources, get_all_deps(),
                          exclusives=exclusives or {})

    self.module = module
    self.antlr_version = antlr_version
