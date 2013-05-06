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

import os

from twitter.pants.base.target import Target


def resolve_target_sources(target_sources, extension=None, relative_to_target_base=False):
  """Given a list of pants targets, extract their sources as a list.

  Filters against the extension if given and optionally returns the paths relative to the target
  base.
  """
  resolved_sources = []
  for resolved in Target.resolve_all(target_sources):
    if hasattr(resolved, 'sources'):
      resolved_sources.extend(
        source if relative_to_target_base else os.path.join(resolved.target_base, source)
        for source in resolved.sources if not extension or source.endswith(extension)
      )
  return resolved_sources


from .annotation_processor import AnnotationProcessor
from .anonymous import AnonymousDeps
from .artifact import Artifact
from .benchmark import Benchmark
from .credentials import Credentials
from .doc import Page, Wiki
from .exclude import Exclude
from .exportable_jvm_library import ExportableJvmLibrary
from .gem import Gem
from .hadoop_binary import TwitterHadoopBinary
from .idl_jar_thrift_library import IdlJvmThriftLibrary
from .internal import InternalTarget
from .jar_dependency import JarDependency
from .jar_library import JarLibrary
from .java_antlr_library import JavaAntlrLibrary
from .java_library import JavaLibrary
from .java_thrift_library import JavaThriftLibrary
from .java_thriftstore_dml_library import JavaThriftstoreDMLLibrary
from .java_protobuf_library import JavaProtobufLibrary
from .java_tests import JavaTests
from .jvm_binary import Bundle, JvmApp, JvmBinary
from .jvm_target import JvmTarget
from .oink_query import OinkQuery
from .pants_target import Pants
from .python_artifact import PythonArtifact
from .python_binary import PythonBinary
from .python_egg import PythonEgg
from .python_library import PythonLibrary
from .python_antlr_library import PythonAntlrLibrary
from .python_thrift_library import PythonThriftLibrary
from .python_requirement import PythonRequirement
from .python_target import PythonTarget
from .python_tests import PythonTests, PythonTestSuite
from .repository import Repository
from .ruby_thrift_library import RubyThriftLibrary
from .ruby_target import RubyTarget
from .resources import Resources
from .scala_library import ScalaLibrary
from .scala_tests import ScalaTests
from .scalac_plugin import ScalacPlugin
from .sources import SourceRoot
from .thrift_library import ThriftJar, ThriftLibrary
from .with_sources import TargetWithSources


__all__ = (
  'AnnotationProcessor',
  'AnonymousDeps',
  'Artifact',
  'Benchmark',
  'Bundle',
  'Credentials',
  'Exclude',
  'ExportableJvmLibrary',
  'Gem',
  'IdlJvmThriftLibrary',
  'InternalTarget',
  'JarDependency',
  'JarLibrary',
  'JavaAntlrLibrary',
  'JavaLibrary',
  'JavaThriftLibrary',
  # TODO(Anand) Remove this from pants proper when a code adjoinment mechanism exists
  # or ok if/when thriftstore is open sourced as well..
  'JavaThriftstoreDMLLibrary',
  'JavaProtobufLibrary',
  'JavaTests',
  'JvmApp',
  'JvmBinary',
  'JvmTarget',
  'OinkQuery',
  'Page',
  'Pants',
  'PythonArtifact',
  'PythonBinary',
  'PythonEgg',
  'PythonLibrary',
  'PythonTarget',
  'PythonAntlrLibrary',
  'PythonRequirement',
  'PythonThriftLibrary',
  'PythonTests',
  'PythonTestSuite',
  'Repository',
  'Resources',
  'RubyTarget',
  'RubyThriftLibrary',
  'ScalaLibrary',
  'ScalaTests',
  'ScalacPlugin',
  'SourceRoot',
  'TargetWithSources',
  'ThriftJar',
  'ThriftLibrary',
  'TwitterHadoopBinary',
  'Wiki'
)
