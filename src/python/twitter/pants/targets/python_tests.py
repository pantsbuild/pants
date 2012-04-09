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

from twitter.common.quantity import Amount, Time
from twitter.pants.targets.python_target import PythonTarget


class PythonTests(PythonTarget):
  def __init__(self, name, sources, resources=None, dependencies=None,
               timeout=Amount(2, Time.MINUTES),
               soft_dependencies=False):
    """
      name / sources / resources / dependencies: See PythonLibrary target

      timeout: Amount of time before this test should be considered timed-out
                [Default: 2 minutes]
      soft_dependencies: Whether or not we should ignore dependency resolution
                         errors for this test.  [Default: False]
    """
    self._timeout = timeout
    self._soft_dependencies = bool(soft_dependencies)
    PythonTarget.__init__(self, name, sources, resources, dependencies)

  @property
  def timeout(self):
    return self._timeout


class PythonTestSuite(PythonTarget):
  def __init__(self, name, dependencies=None):
    PythonTarget.__init__(self, name, (), (), dependencies)
