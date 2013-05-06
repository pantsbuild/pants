# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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
from twitter.pants.base import manual
from .ruby_target import RubyTarget


@manual.builddict(tags=["ruby"])
class RubyThriftLibrary(RubyTarget):
  """Generates a stub Ruby library from thrift IDL files."""

  def __init__(self, name,
               sources=None,
               dependencies=None,
               provides=None):
    """
    :param name: Name of library
    :param source: thrift source file
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    """
    RubyTarget.__init__(self, name, sources, dependencies, provides)
