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

from annotation_processor import AnnotationProcessor
from artifact import Artifact
from credentials import Credentials
from exclude import Exclude
from exportable_jvm_library import ExportableJvmLibrary
from internal import InternalTarget
from jar_dependency import JarDependency
from jar_library import JarLibrary
from java_library import JavaLibrary
from java_thrift_library import JavaThriftLibrary
from java_protobuf_library import JavaProtobufLibrary
from java_tests import JavaTests
from jvm_binary import Bundle, JvmApp, JvmBinary
from jvm_target import JvmTarget
from pants_target import Pants
from python_binary import PythonBinary
from python_egg import PythonEgg
from python_library import PythonLibrary
from python_antlr_library import PythonAntlrLibrary
from python_thrift_library import PythonThriftLibrary
from python_target import PythonTarget
from python_tests import PythonTests, PythonTestSuite
from repository import Repository
from scala_library import ScalaLibrary
from scala_tests import ScalaTests
from sources import SourceRoot
from with_sources import TargetWithSources
from doc import Doc

__all__ = [
  'AnnotationProcessor',
  'Artifact',
  'Bundle',
  'Credentials',
  'Exclude',
  'ExportableJvmLibrary',
  'InternalTarget',
  'JarDependency',
  'JarLibrary',
  'JavaLibrary',
  'JavaThriftLibrary',
  'JavaProtobufLibrary',
  'JavaTests',
  'JvmApp',
  'JvmBinary',
  'JvmTarget',
  'Pants',
  'PythonBinary',
  'PythonEgg',
  'PythonLibrary',
  'PythonTarget',
  'PythonAntlrLibrary',
  'PythonThriftLibrary',
  'PythonTests',
  'PythonTestSuite',
  'Repository',
  'ScalaLibrary',
  'ScalaTests',
  'SourceRoot',
  'TargetWithSources',
  'Doc'
]
