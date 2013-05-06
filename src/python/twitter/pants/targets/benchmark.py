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

from .jvm_target import JvmTarget
from .resources import Resources


class Benchmark(JvmTarget):
  """Defines a target that run a caliper benchmark."""

  def __init__(self,
               name,
               sources = None,
               java_sources = None,
               dependencies = None,
               excludes = None,
               resources = None):

    JvmTarget.__init__(self,
                       name,
                       sources,
                       dependencies,
                       excludes)

    self.java_sources = java_sources
    self.resources = list(self.resolve_all(resources, Resources))
