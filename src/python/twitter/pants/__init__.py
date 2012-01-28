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

_VERSION = '0.0.3'

def get_version():
  return _VERSION


_BUILD_ROOT = None

def get_buildroot():
  global _BUILD_ROOT
  if not _BUILD_ROOT:
    if 'PANTS_BUILD_ROOT' in os.environ:
      _BUILD_ROOT = os.path.realpath(os.environ['PANTS_BUILD_ROOT'])
    else:
      build_root = os.path.abspath(os.getcwd())
      while not os.path.exists(os.path.join(build_root, '.git')):
        if build_root != os.path.dirname(build_root):
          build_root = os.path.dirname(build_root)
        else:
          print >> sys.stderr, 'Could not find .git root!'
          sys.exit(1)
      _BUILD_ROOT = os.path.realpath(build_root)
  return _BUILD_ROOT

import fnmatch
import glob

from twitter.pants.base import Fileset

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
    for base, _, files in os.walk(root):
      for filename in files:
        path = os.path.relpath(os.path.normpath(os.path.join(base, filename)), root)
        for globspec in globspecs:
          if fnmatch.fnmatch(path, globspec):
            yield path

  return Fileset(lambda: set(recursive_globs()))


from twitter.pants.targets import *

# aliases
annotation_processor = AnnotationProcessor
artifact = Artifact
bundle = Bundle
doc = Doc
egg = PythonEgg
exclude = Exclude
fancy_pants = Pants
jar = JarDependency
jar_library = JarLibrary
java_library = JavaLibrary
java_protobuf_library = JavaProtobufLibrary
java_tests = JavaTests
java_thrift_library = JavaThriftLibrary
jvm_binary = JvmBinary
jvm_app = JvmApp
python_binary = PythonBinary
python_library = PythonLibrary
python_antlr_library = PythonAntlrLibrary
python_thrift_library = PythonThriftLibrary
python_tests = PythonTests
python_test_suite = PythonTestSuite
repo = Repository
scala_library = ScalaLibrary
scala_tests = ScalaTests
source_root = SourceRoot

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

def is_doc(target):
  """Returns True if the target is a documentation target."""

  return isinstance(target, Doc)

def is_java(target):
  """Returns True if the target has or generates java sources."""

  return isinstance(target, JavaLibrary) or (
    isinstance(target, AnnotationProcessor)) or (
    isinstance(target, JavaProtobufLibrary)) or (
    isinstance(target, JavaTests)) or (
    is_thrift(target))

def is_thrift(target):
  """Returns True if the target has thrift IDL sources."""

  return isinstance(target, JavaThriftLibrary)

def is_apt(target):
  """Returns True if the target exports an annotation processor."""

  return isinstance(target, AnnotationProcessor)

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

# bind tasks and goals below utility functions they use from above
from twitter.pants.tasks import Config, Context, Goal, Group, Task, TaskError
goal = Goal
group = Group

__all__ = (
  'annotation_processor',
  'artifact',
  'bundle',
  'exclude',
  'egg',
  'get_buildroot',
  'get_version',
  'globs',
  'goal',
  'group',
  'is_apt',
  'is_doc',
  'is_exported',
  'is_internal',
  'is_java',
  'is_jvm',
  'is_python',
  'is_scala',
  'is_test',
  'jar',
  'jar_library',
  'java_library',
  'java_protobuf_library',
  'java_tests',
  'java_thrift_library',
  'jvm_app',
  'jvm_binary',
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
  'source_root',
  'doc',
  'Config',
  'Context',
  'JavaLibrary',
  'JavaTests',
  'Task',
  'TaskError',
)
