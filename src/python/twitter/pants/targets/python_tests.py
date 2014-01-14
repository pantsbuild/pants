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
  """Tests a Python library."""

  def __init__(self,
               name,
               sources,
               resources=None,
               dependencies=None,
               timeout=Amount(2, Time.MINUTES),
               coverage=None,
               soft_dependencies=False,
               entry_point='pytest'):
    """
    :param name: See PythonLibrary target
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: See PythonLibrary target
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param timeout: Amount of time before this test should be considered timed-out.
    :param coverage: the module(s) whose coverage should be generated, e.g.
      'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
    :param soft_dependencies: Whether or not we should ignore dependency resolution
      errors for this test.
    :param entry_point: The entry point to use to run the tests.
    """
    self._timeout = timeout
    self._soft_dependencies = bool(soft_dependencies)
    self._coverage = maybe_list(coverage) if coverage is not None else []
    self._entry_point = entry_point
    PythonTarget.__init__(self, name, sources, resources, dependencies)
    self.add_labels('python', 'tests')

  @property
  def timeout(self):
    return self._timeout

  @property
  def coverage(self):
    return self._coverage

  @property
  def entry_point(self):
    return self._entry_point


class PythonTestSuite(PythonTarget):
  """Tests one or more python test targets."""

  def __init__(self, name, dependencies=None):
    PythonTarget.__init__(self, name, (), (), dependencies)
