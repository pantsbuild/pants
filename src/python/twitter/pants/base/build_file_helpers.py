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

import os

from twitter.pants.targets.annotation_processor import AnnotationProcessor
from twitter.pants.targets.doc import Page
from twitter.pants.targets.java_agent import JavaAgent
from twitter.pants.targets.java_antlr_library import JavaAntlrLibrary
from twitter.pants.targets.java_library import JavaLibrary
from twitter.pants.targets.java_protobuf_library import JavaProtobufLibrary
from twitter.pants.targets.java_tests import JavaTests
from twitter.pants.targets.java_thrift_library import JavaThriftLibrary
from twitter.pants.targets.jvm_binary import JvmBinary
from twitter.pants.targets.python_antlr_library import PythonAntlrLibrary
from twitter.pants.targets.python_binary import PythonBinary
from twitter.pants.targets.python_library import PythonLibrary
from twitter.pants.targets.python_tests import PythonTests, PythonTestSuite
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary
from twitter.pants.targets.resources import Resources
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets.sources import SourceRoot


def maven_layout(basedir=None):
  """Sets up typical maven project source roots for all built-in pants target types.

  Shortcut for ``source_root('src/main/java', *java targets*)``,
  ``source_root('src/main/python', *python targets*)``, ...

  :param string basedir: Instead of using this BUILD file's directory as
    the base of the source tree, use a subdirectory. E.g., instead of
    expecting to find java files in ``src/main/java``, expect them in
    ``**basedir**/src/main/java``.
  """

  def root(path, *types):
    SourceRoot.register(os.path.join(basedir, path) if basedir else path, *types)

  root('src/main/antlr', JavaAntlrLibrary, Page, PythonAntlrLibrary)
  root('src/main/java', AnnotationProcessor, JavaAgent, JavaLibrary, JvmBinary, Page)
  root('src/main/protobuf', JavaProtobufLibrary, Page)
  root('src/main/python', Page, PythonBinary, PythonLibrary)
  root('src/main/resources', Page, Resources)
  root('src/main/scala', JvmBinary, Page, ScalaLibrary)
  root('src/main/thrift', JavaThriftLibrary, Page, PythonThriftLibrary)

  root('src/test/java', JavaLibrary, JavaTests, Page)
  root('src/test/python', Page, PythonLibrary, PythonTests, PythonTestSuite)
  root('src/test/resources', Page, Resources)
  root('src/test/scala', JavaTests, Page, ScalaLibrary, ScalaTests)
