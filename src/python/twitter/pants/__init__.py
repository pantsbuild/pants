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
import sys
import fnmatch
import glob

from twitter.pants.base import Fileset
from twitter.pants.targets import *

# aliases
annotation_processor = AnnotationProcessor
artifact = Artifact
egg = PythonEgg
exclude = Exclude
fancy_pants = Pants
jar = JarDependency
jar_library = JarLibrary
java_library = JavaLibrary
java_protobuf_library = JavaProtobufLibrary
java_tests = JavaTests
java_thrift_library = JavaThriftLibrary
python_binary = PythonBinary
python_library = PythonLibrary
python_antlr_library = PythonAntlrLibrary
python_thrift_library = PythonThriftLibrary
python_tests = PythonTests
python_test_suite = PythonTestSuite
repo = Repository
scala_library = ScalaLibrary
scala_tests = ScalaTests

def globs(*globspecs):
  """Returns a Fileset that combines the lists of files returned by glob.glob for each globspec."""

  def combine(files, globspec):
    return files ^ set(glob.glob(globspec))
  return Fileset(lambda: reduce(combine, globspecs, set()))

def rglobs(*globspecs):
  """Returns a Fileset that does a recursive scan under the current directory combining the lists of
  files returned that would be returned by glob.glob for each globspec."""

  root = os.curdir
  def recursive_globs():
    for base, dirs, files in os.walk(root):
      for file in files:
        path = os.path.relpath(os.path.normpath(os.path.join(base, file)), root)
        for globspec in globspecs:
          if fnmatch.fnmatch(path, globspec):
            yield path

  return Fileset(lambda: set(recursive_globs()))

def has_sources(target):
  """Returns True if the target has sources."""

  return isinstance(target, TargetWithSources)

def is_exported(target):
  """Returns True if the target provides an artifact exportable from the repo."""

  return isinstance(target, ExportableJvmLibrary) and target.provides

def is_internal(target):
  """Returns True if the target is internal to the repo (ie: it might have dependencies)."""

  return isinstance(target, InternalTarget)

def is_jvm(target):
  """Returns True if the target produces jvm bytecode."""

  return isinstance(target, JvmTarget)

def is_apt(target):
  """Returns True if the target produces annotation processors."""

  return isinstance(target, AnnotationProcessor)

def has_jvm_targets(targets):
  """Returns true if the given sequence of targets contains at least one jvm target as determined
  by is_jvm(...)"""

  return len(list(extract_jvm_targets(targets))) > 0

def extract_jvm_targets(targets):
  """Returns an iterator over the jvm targets the given sequence of targets resolve to.  The given
  targets can be a mix of types and any non jvm targets (as determined by is_jvm(...) will be
  filtered out from the returned iterator."""

  for target in targets:
    if target is None:
      print >> sys.stderr, 'Warning! Null target!'
      continue
    for real_target in target.resolve():
      if is_jvm(real_target):
        yield real_target

def is_java(target):
  """Returns True if the target has or generates java sources."""

  return isinstance(target, JavaLibrary) or (
    isinstance(target, JavaProtobufLibrary)) or (
    isinstance(target, JavaTests)) or (
    isinstance(target, JavaThriftLibrary))

def is_python(target):
  """Returns True if the target has python sources."""

  return isinstance(target, PythonTarget) or isinstance(target, PythonEgg)

def is_scala(target):
  """Returns True if the target has scala sources."""

  return isinstance(target, ScalaLibrary) or isinstance(target, ScalaTests)

def is_test(t):
  """Returns True if the target is comprised of tests."""

  return isinstance(t, JavaTests) or isinstance(t, ScalaTests) or isinstance(t, PythonTests)

# bind this as late as possible
pants = fancy_pants
__all__ = (
  'annotation_processor',
  'artifact',
  'exclude',
  'egg',
  'globs',
  'jar',
  'jar_library',
  'java_library',
  'java_protobuf_library',
  'java_tests',
  'java_thrift_library',
  'pants',
  'python_antlr_library',
  'python_binary',
  'python_library',
  'python_tests',
  'python_test_suite',
  'python_thrift_library',
  'repo',
  'rglobs',
  'scala_library',
  'scala_tests',
)
