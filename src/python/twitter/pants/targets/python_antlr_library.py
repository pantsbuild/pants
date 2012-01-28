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
from python_target import PythonTarget
from pants_target import Pants

class PythonAntlrLibrary(PythonTarget):
  def __init__(self, name, module,
               antlr_version = '3.1.3',
               sources = None,
               resources = None,
               dependencies = None):
    """
      name = Name of library
      package = Python package to generate the parser in (there is no directive for this in ANTLR)
      sources = antlr source files
      resources = non-Python resources, e.g. templates, keys, other data (it is
        recommended that your application uses the pkgutil package to access these
        resources in a .zip-module friendly way.)
      dependencies = other PythonLibraries, Eggs or internal Pants targets
    """

    def get_all_deps():
      all_deps = OrderedSet()
      all_deps.update(Pants('3rdparty/python:antlr-%s' % antlr_version).resolve())
      if dependencies:
        all_deps.update(dependencies)
      return all_deps

    PythonTarget.__init__(self, name, sources, resources, get_all_deps())

    self.module = module
    self.antlr_version = antlr_version
