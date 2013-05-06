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

from twitter.common.collections import maybe_list
from twitter.common.quantity import Amount, Time
from twitter.pants.targets.python_target import PythonTarget


class PythonTests(PythonTarget):
  def __init__(self, name, sources,
               resources=None,
               dependencies=None,
               timeout=Amount(2, Time.MINUTES),
               coverage=None,
               soft_dependencies=False):
    """
      name / sources / resources / dependencies: See PythonLibrary target

      timeout: Amount of time before this test should be considered timed-out
                [Default: 2 minutes]
      soft_dependencies: Whether or not we should ignore dependency resolution
                         errors for this test.  [Default: False]
      coverage: the module(s) whose coverage should be generated, e.g.
                'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
    """
    self._timeout = timeout
    self._soft_dependencies = bool(soft_dependencies)
    self._coverage = maybe_list(coverage) if coverage is not None else []
    PythonTarget.__init__(self, name, sources, resources, dependencies)
    self.add_labels('python', 'tests')

  @property
  def timeout(self):
    return self._timeout

  @property
  def coverage(self):
    return self._coverage


class PythonTestSuite(PythonTarget):
  def __init__(self, name, dependencies=None):
    PythonTarget.__init__(self, name, (), (), dependencies)
