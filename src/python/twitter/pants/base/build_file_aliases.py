# =================================================================================================
# Copyright 2011 Twitter, Inc.
# -------------------------------------------------------------------------------------------------
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
# =================================================================================================

from twitter.pants.targets.annotation_processor import AnnotationProcessor
from twitter.pants.targets.artifact import Artifact
from twitter.pants.targets.benchmark import Benchmark
from twitter.pants.targets.credentials import Credentials
from twitter.pants.targets.doc import Page, Wiki
from twitter.pants.targets.exclude import Exclude
from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.jar_library import JarLibrary
from twitter.pants.targets.java_agent import JavaAgent
from twitter.pants.targets.java_antlr_library import JavaAntlrLibrary
from twitter.pants.targets.java_library import JavaLibrary
from twitter.pants.targets.java_protobuf_library import JavaProtobufLibrary
from twitter.pants.targets.java_tests import JavaTests
from twitter.pants.targets.java_thrift_library import JavaThriftLibrary
from twitter.pants.targets.jvm_binary import Bundle, JvmApp, JvmBinary
from twitter.pants.targets.pants_target import Pants
from twitter.pants.targets.python_antlr_library import PythonAntlrLibrary
from twitter.pants.targets.python_artifact import PythonArtifact
from twitter.pants.targets.python_binary import PythonBinary
from twitter.pants.targets.python_egg import PythonEgg
from twitter.pants.targets.python_library import PythonLibrary
from twitter.pants.targets.python_requirement import PythonRequirement
from twitter.pants.targets.python_tests import PythonTests, PythonTestSuite
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary
from twitter.pants.targets.repository import Repository
from twitter.pants.targets.resources import Resources
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets.scalac_plugin import ScalacPlugin
from twitter.pants.targets.sources import SourceRoot


# aliases
annotation_processor = AnnotationProcessor
artifact = Artifact
benchmark = Benchmark
bundle = Bundle
credentials = Credentials
dependencies = jar_library = JarLibrary
egg = PythonEgg
exclude = Exclude
fancy_pants = Pants
jar = JarDependency
java_agent = JavaAgent
java_library = JavaLibrary
java_antlr_library = JavaAntlrLibrary
java_protobuf_library = JavaProtobufLibrary
junit_tests = java_tests = JavaTests
java_thrift_library = JavaThriftLibrary
jvm_binary = JvmBinary
jvm_app = JvmApp
page = Page
python_artifact = setup_py = PythonArtifact
python_binary = PythonBinary
python_library = PythonLibrary
python_antlr_library = PythonAntlrLibrary
python_requirement = PythonRequirement
python_thrift_library = PythonThriftLibrary
python_tests = PythonTests
python_test_suite = PythonTestSuite
repo = Repository
resources = Resources
scala_library = ScalaLibrary
scala_specs = scala_tests = ScalaTests
scalac_plugin = ScalacPlugin
source_root = SourceRoot
wiki = Wiki
