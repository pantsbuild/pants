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

def resolve_target_sources(target_sources, extension):
  """given a list of pants targets, extract their sources as a list"""
  resolved_sources = []

  if target_sources:
    for target in target_sources:
      for resolved in target.resolve():
        if hasattr(resolved, 'sources'):
          resolved_sources.extend(os.path.join(resolved.target_base, source)
            for source in resolved.sources if source.endswith(extension))
  return resolved_sources

from twitter.pants.targets.annotation_processor import AnnotationProcessor
from twitter.pants.targets.artifact import Artifact
from twitter.pants.targets.credentials import Credentials
from twitter.pants.targets.doc import Doc, Page, Wiki
from twitter.pants.targets.exclude import Exclude
from twitter.pants.targets.exportable_jvm_library import ExportableJvmLibrary
from twitter.pants.targets.internal import InternalTarget
from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.jar_library import JarLibrary
from twitter.pants.targets.java_library import JavaLibrary
from twitter.pants.targets.java_thrift_library import JavaThriftLibrary
from twitter.pants.targets.java_thriftstore_dml_library import JavaThriftstoreDMLLibrary
from twitter.pants.targets.java_protobuf_library import JavaProtobufLibrary
from twitter.pants.targets.java_tests import JavaTests
from twitter.pants.targets.jvm_binary import Bundle, JvmApp, JvmBinary
from twitter.pants.targets.jvm_target import JvmTarget
from twitter.pants.targets.pants_target import Pants
from twitter.pants.targets.python_binary import PythonBinary
from twitter.pants.targets.python_egg import PythonEgg
from twitter.pants.targets.python_library import PythonLibrary
from twitter.pants.targets.python_antlr_library import PythonAntlrLibrary
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary
from twitter.pants.targets.python_requirement import PythonRequirement
from twitter.pants.targets.python_target import PythonTarget
from twitter.pants.targets.python_tests import PythonTests, PythonTestSuite
from twitter.pants.targets.repository import Repository
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets.scalac_plugin import ScalacPlugin
from twitter.pants.targets.sources import SourceRoot
from twitter.pants.targets.with_sources import TargetWithSources

__all__ = [
  'AnnotationProcessor',
  'Artifact',
  'Bundle',
  'Credentials',
  'Doc',
  'Exclude',
  'ExportableJvmLibrary',
  'InternalTarget',
  'JarDependency',
  'JarLibrary',
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
  'Page',
  'Pants',
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
  'ScalaLibrary',
  'ScalaTests',
  'ScalacPlugin',
  'SourceRoot',
  'TargetWithSources',
  'Wiki'
]
