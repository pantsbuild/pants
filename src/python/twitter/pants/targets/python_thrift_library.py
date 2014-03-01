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

from twitter.pants.base.build_manual import manual

from .python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonThriftLibrary(PythonTarget):
  """Generates a stub Python library from thrift IDL files."""

  def __init__(self, name,
               sources=None,
               resources=None,
               dependencies=None,
               provides=None,
               exclusives=None):
    """
    :param name: Name of library
    :param sources: thrift source files (If more than one tries to use the same
      namespace, beware https://issues.apache.org/jira/browse/THRIFT-515)
    :param resources: non-Python resources, e.g. templates, keys, other data (it is
      recommended that your application uses the pkgutil package to access these
      resources in a .zip-module friendly way.)
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """
    super(PythonThriftLibrary, self).__init__(name, sources, resources, dependencies, provides,
                                              exclusives=exclusives)
