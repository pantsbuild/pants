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

LOGGING_EXCLUDES = [
  Exclude(org = 'ch.qos.logback'),
  Exclude(org = 'commons-logging', name = 'commons-logging'),
  Exclude(org = 'log4j'),
  Exclude(org = 'org.slf4j'),
]
# The storm cluster provides the appropriate versions of these jars.
ON_STORM_CLUSTER_EXCLUDES = [
  Exclude(org = 'storm', name = 'storm'),
  Exclude(org = 'backtype', name = 'jzmq'),
  Exclude(org = 'ch.qos.logback', name = 'logback-classic'),
  Exclude(org = 'clj-time', name = 'clj-time'),
  Exclude(org = 'com.google.guava'),
  Exclude(org = 'com.googlecode.disruptor', name = 'disruptor'),
  Exclude(org = 'com.googlecode.json-simple', name = 'json-simple'),
  Exclude(org = 'com.netflix.curator', name = 'curator-framework'),
  Exclude(org = 'com.twitter.storm', name = 'carbonite'),
  Exclude(org = 'commons-io', name = 'commons-io'),
  Exclude(org = 'compojure', name = 'compojure'),
  Exclude(org = 'hiccup', name = 'hiccup'),
  Exclude(org = 'org.apache.commons', name = 'commons-exec'),
  Exclude(org = 'org.apache.httpcomponents', name = 'httpclient'),
  Exclude(org = 'org.clojure', name = 'clojure'),
  Exclude(org = 'org.clojure', name = 'math.numeric-tower'),
  Exclude(org = 'org.clojure', name = 'tools.logging'),
  Exclude(org = 'org.yaml', name = 'snakeyaml'),
  Exclude(org = 'ring', name = 'ring-jetty-adapter'),
  Exclude(org = 'storm', name = 'jgrapht'),
  Exclude(org = 'storm', name = 'libthrift7'),
  Exclude(org = 'storm', name = 'tools.cli'),
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
      deploy_excludes=(deploy_excludes or []) + LOGGING_EXCLUDES + ON_STORM_CLUSTER_EXCLUDES,
      configurations=None
    )
