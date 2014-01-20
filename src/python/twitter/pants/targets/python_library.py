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

from twitter.pants.targets.python_target import PythonTarget


class PythonLibrary(PythonTarget):
  """Produces a Python library."""

  def __init__(self,
               name,
               sources=(),
               resources=(),
               dependencies=(),
               provides=None,
               compatibility=None,
               exclusives=None):
    """
    :param name: Name of library
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param Artifact provides:
      The :class:`twitter.pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """
    PythonTarget.__init__(self,
        name,
        sources=sources,
        resources=resources,
        dependencies=dependencies,
        provides=provides,
        compatibility=compatibility,
        exclusives=exclusives,
    )
