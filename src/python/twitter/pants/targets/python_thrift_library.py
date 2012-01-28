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

class PythonThriftLibrary(PythonTarget):
  _VALID_LIBRARIES = ['0.5', '0.7']

  def __init__(self, name,
               sources = None,
               resources = None,
               dependencies = None,
               thrift_library = '0.7'):
    """
      name = Name of library
      source = thrift source file
      resources = non-Python resources, e.g. templates, keys, other data (it is
        recommended that your application uses the pkgutil package to access these
        resources in a .zip-module friendly way.)
      dependencies = other PythonLibraries, Eggs or internal Pants targets
    """
    assert thrift_library in PythonThriftLibrary._VALID_LIBRARIES, \
      'Specified thrift library %s, but only %s are valid' % (
        thrift_library, ' & '.join(PythonThriftLibrary._VALID_LIBRARIES))

    def get_all_deps():
      all_deps = OrderedSet()
      all_deps.update(Pants('3rdparty/python:thrift-%s' % thrift_library).resolve())
      if dependencies:
        all_deps.update(dependencies)
      return all_deps

    PythonTarget.__init__(self, name, sources, resources, get_all_deps())
