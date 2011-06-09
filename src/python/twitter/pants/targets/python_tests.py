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

class PythonTests(PythonTarget):
  def __init__(self, name, sources, resources = None, dependencies = None, is_meta = False):
    PythonTarget.__init__(
      self,
      'tests/python',
      name,
      sources,
      resources,
      dependencies,
      is_meta)

class PythonTestSuite(PythonTarget):
  def __init__(self, name, dependencies = None):
    PythonTarget.__init__(
      self,
      'tests/python',
      name,
      [],
      [],
      dependencies,
      False)
