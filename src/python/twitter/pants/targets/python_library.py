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

from python_target import PythonTarget

class PythonLibrary(PythonTarget):
  def __init__(self, name, sources=(), resources=(), dependencies=(), module=""):
    """
      name = Name of library
      sources = Python source files
      resources = non-Python resources, e.g. templates, keys, other data (it is
        recommended that your application uses the pkgutil package to access these
        resources in a .zip-module friendly way.)
      dependencies = other PythonLibraries, Eggs or internal Pants targets
      module = everything beneath module is relative to this module name, None if root namespace
    """
    self._module = module
    PythonTarget.__init__(self, name, sources, resources, dependencies)

  def _create_template_data(self):
    return PythonTarget._create_template_data(self).extend(module=self._module)
