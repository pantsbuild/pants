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

import re

from twitter.pants.base import manual, TargetDefinitionException

from .jar_dependency import JarDependency
from .java_thrift_library import JavaThriftLibrary
from .thrift_library import ThriftJar


@manual.builddict(tags=["java"])
class IdlJvmThriftLibrary(JavaThriftLibrary):
  """Creates a java thrift library from an idl jar

  Takes in an idl-only thrift jar and expands it to a JavaThriftLibrary with sources from the
  jar and the thrift_jar itself as the dependency.
  """
  # TODO (tina): keeping this around for now to be consistent with JavaThriftLibrary, but we need
  # to clean this up: https://jira.twitter.biz/browse/DPB-364
  _RPC_STYLE_DEFAULT = 'sync'

  def __init__(self,
               name,
               thrift_jar,
               language,
               excludes=None,
               rpc_style=_RPC_STYLE_DEFAULT,
               provided_by=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param thrift_jar: A :class:`twitter.pants.targets.thrift_library.ThriftJar` that contains
      the IDL files this target will generate sources from.
    :param excludes: List of :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param language: The language used to generate the output files.
      One of 'java' or 'scala'.
    :param rpc_style: An optional rpc style to generate service stubs with.
      One of 'sync', 'finagle' or 'ostrich' with a default of 'sync'.
    :param provided_by: Published classfile jar if not default pants name.
    """
    JavaThriftLibrary.__init__(self, name=name, sources=[], provides=None,
                               dependencies=[thrift_jar], excludes=excludes, language=language,
                               rpc_style=rpc_style, compiler='scrooge')
    self.idl_jar = thrift_jar
    if not isinstance(thrift_jar, ThriftJar):
      raise TargetDefinitionException(
        self, "thrift_jar must be a ThriftJar instance, but was %s" % thrift_jar)

    # TODO (tina): Consolidate references to -only in a util https://jira.twitter.biz/browse/DPB-363
    provided_name = re.sub(r"-only$", "", thrift_jar.name)
    self.provided_by = provided_by or JarDependency(org=thrift_jar.org, name=provided_name,
                                                    rev=thrift_jar.rev).intransitive()
    if not isinstance(self.provided_by, JarDependency):
      raise TargetDefinitionException(self, "provided_by for target must be a JarDependency: %s"
                                            % self.provided_by)
