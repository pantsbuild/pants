# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.targets.annotation_processor import AnnotationProcessor
from pants.targets.artifact import Artifact
from pants.targets.benchmark import Benchmark
from pants.targets.credentials import Credentials
from pants.targets.doc import Page, Wiki
from pants.targets.exclude import Exclude
from pants.targets.jar_dependency import JarDependency
from pants.targets.jar_library import JarLibrary
from pants.targets.java_agent import JavaAgent
from pants.targets.java_antlr_library import JavaAntlrLibrary
from pants.targets.java_library import JavaLibrary
from pants.targets.java_protobuf_library import JavaProtobufLibrary
from pants.targets.java_tests import JavaTests
from pants.targets.java_thrift_library import JavaThriftLibrary
from pants.targets.jvm_binary import Bundle, JvmApp, JvmBinary
from pants.targets.pants_target import Pants
from pants.targets.python_antlr_library import PythonAntlrLibrary
from pants.targets.python_artifact import PythonArtifact
from pants.targets.python_binary import PythonBinary
from pants.targets.python_egg import PythonEgg
from pants.targets.python_library import PythonLibrary
from pants.targets.python_requirement import PythonRequirement
from pants.targets.python_tests import PythonTestSuite, PythonTests
from pants.targets.python_thrift_library import PythonThriftLibrary
from pants.targets.repository import Repository
from pants.targets.resources import Resources
from pants.targets.scala_library import ScalaLibrary
from pants.targets.scala_tests import ScalaTests
from pants.targets.scalac_plugin import ScalacPlugin
from pants.targets.sources import SourceRoot


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
