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

from __future__ import print_function

from twitter.pants.targets import (
    AnnotationProcessor,
    Artifact,
    Benchmark,
    Bundle,
    Credentials,
    JarLibrary,
    PythonEgg,
    Exclude,
    JarDependency,
    JavaLibrary,
    JavaAntlrLibrary,
    JavaProtobufLibrary,
    JavaTests,
    JavaThriftLibrary,
    JavaThriftstoreDMLLibrary,
    JvmApp,
    JvmBinary,
    OinkQuery,
    Page,
    Pants,
    PythonArtifact,
    PythonBinary,
    PythonLibrary,
    PythonAntlrLibrary,
    PythonRequirement,
    PythonThriftLibrary,
    PythonTests,
    PythonTestSuite,
    Repository,
    Resources,
    RubyThriftLibrary,
    ScalaLibrary,
    ScalaTests,
    ScalacPlugin,
    SourceRoot,
    ThriftJar,
    ThriftLibrary,
    Wiki)

from twitter.pants.tasks.extract import Extract

# aliases
annotation_processor = AnnotationProcessor
artifact = Artifact
benchmark = Benchmark
bundle = Bundle
compiled_idl = Extract.compiled_idl
credentials = Credentials
dependencies = jar_library = JarLibrary
egg = PythonEgg
exclude = Exclude
fancy_pants = Pants
jar = JarDependency
java_library = JavaLibrary
java_antlr_library = JavaAntlrLibrary
java_protobuf_library = JavaProtobufLibrary
junit_tests = java_tests = JavaTests
java_thrift_library = JavaThriftLibrary
# TODO(Anand) Remove this from pants proper when a code adjoinment mechanism exists
# or ok if/when thriftstore is open sourced as well
java_thriftstore_dml_library = JavaThriftstoreDMLLibrary
jvm_binary = JvmBinary
jvm_app = JvmApp
oink_query = OinkQuery
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
ruby_thrift_library = RubyThriftLibrary
scala_library = ScalaLibrary
scala_specs = scala_tests = ScalaTests
scalac_plugin = ScalacPlugin
source_root = SourceRoot
thrift_jar = ThriftJar
thrift_library = ThriftLibrary
wiki = Wiki
