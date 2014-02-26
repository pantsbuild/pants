# ==================================================================================================
# Copyright 2014 Twitter, Inc.
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

from twitter.pants.targets.jvm_binary import JvmBinary
from twitter.pants.targets.exclude import Exclude

BLACKLIST_EXCLUDES = [
  Exclude(org = 'log4j'), #There should only be a single logger implementation per JVM, and that's logback on storm. 
]

# The storm cluster provides the appropriate versions of these jars.
ON_STORM_CLUSTER_EXCLUDES = [
  Exclude(org = 'storm', name = 'storm'),
  Exclude(org = 'backtype', name = 'jzmq'),
  Exclude(org = 'com.esotericsoftware.kryo', name = 'kryo'),
  Exclude(org = 'com.googlecode.disruptor', name = 'disruptor'),
  Exclude(org = 'ch.qos.logback'),
  Exclude(org = 'org.slf4j'),
  Exclude(org = 'org.clojure', name = 'clojure'),
  Exclude(org = 'org.clojure', name = 'math.numeric-tower'),
  Exclude(org = 'org.clojure', name = 'tools.logging'),
]

class TwitterStormBinary(JvmBinary):
  """A binary that is suitable for running on the Storm cluster.

  Invoking the ``binary`` or ``bundle`` goal on one of these targets creates a binary jar that
  excludes any dependencies already provided by the Storm cluster.
  """
  def __init__(
      self,
      name,
      main,
      basename=None,
      source=None,
      resources=None,
      dependencies=None,
      excludes=[],
      deploy_excludes=[]):

    JvmBinary.__init__(
      self,
      name=name,
      main=main,
      basename=basename,
      source=source,
      resources=resources,
      dependencies=dependencies,
      excludes=excludes,
      deploy_excludes=(deploy_excludes or []) + BLACKLIST_EXCLUDES + ON_STORM_CLUSTER_EXCLUDES,
      configurations=None
    )
