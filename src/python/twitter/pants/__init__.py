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

from __future__ import print_function

import os
import sys

from .version import VERSION as _VERSION


def get_version():
  return _VERSION


_BUILDROOT = None


def get_buildroot():
  """Returns the pants ROOT_DIR, calculating it if needed."""

  global _BUILDROOT
  if not _BUILDROOT:
    if 'PANTS_BUILD_ROOT' in os.environ:
      set_buildroot(os.environ['PANTS_BUILD_ROOT'])
    else:
      buildroot = os.path.abspath(os.getcwd())
      while not os.path.exists(os.path.join(buildroot, 'pants.ini')):
        if buildroot != os.path.dirname(buildroot):
          buildroot = os.path.dirname(buildroot)
        else:
          print('Could not find pants.ini!', file=sys.stderr)
          sys.exit(1)
      set_buildroot(buildroot)
  return _BUILDROOT


def set_buildroot(path):
  """Sets the pants ROOT_DIR.

  Generally only useful for tests.
  """
  if not os.path.exists(path):
    raise ValueError('Build root does not exist: %s' % path)
  global _BUILDROOT
  _BUILDROOT = os.path.realpath(path)


from twitter.pants.scm import Scm

_SCM = None


def get_scm():
  """Returns the pants Scm if any."""
  return _SCM


def set_scm(scm):
  """Sets the pants Scm."""
  if scm is not None:
    if not isinstance(scm, Scm):
      raise ValueError('The scm must be an instance of Scm, given %s' % scm)
    global _SCM
    _SCM = scm


from twitter.common.dirutil import Fileset

globs = Fileset.globs
rglobs = Fileset.rglobs


def is_concrete(target):
  """Returns true if a target resolves to itself."""
  targets = list(target.resolve())
  return len(targets) == 1 and targets[0] == target


from twitter.pants.targets import *

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
scala_library = ScalaLibrary
scala_specs = scala_tests = ScalaTests
scalac_plugin = ScalacPlugin
source_root = SourceRoot
wiki = Wiki


def has_sources(target, extension=None):
  """Returns True if the target has sources.

  If an extension is supplied the target is further checked for at least 1 source with the given
  extension.
  """
  return (target.has_label('sources')
          and (not extension
               or (hasattr(target, 'sources')
                   and any(source.endswith(extension) for source in target.sources))))


def has_resources(target):
  """Returns True if the target has an associated set of Resources."""
  return hasattr(target, 'resources') and target.resources


def is_exported(target):
  """Returns True if the target provides an artifact exportable from the repo."""
  # TODO(John Sirois): fixup predicate dipping down into details here.
  return target.has_label('exportable') and target.provides


def is_internal(target):
  """Returns True if the target is internal to the repo (ie: it might have dependencies)."""
  return target.has_label('internal')


def is_jar(target):
  """Returns True if the target is a jar."""
  return isinstance(target, JarDependency)


def is_jvm(target):
  """Returns True if the target produces jvm bytecode."""
  return target.has_label('jvm')


def has_jvm_targets(targets):
  """Returns true if the given sequence of targets contains at least one jvm target as determined
  by is_jvm(...)"""

  return len(list(extract_jvm_targets(targets))) > 0


def extract_jvm_targets(targets):
  """Returns an iterator over the jvm targets the given sequence of targets resolve to.  The given
  targets can be a mix of types and only valid jvm targets (as determined by is_jvm(...) will be
  returned by the iterator."""

  for target in targets:
    if target is None:
      print('Warning! Null target!', file=sys.stderr)
      continue
    for real_target in target.resolve():
      if is_jvm(real_target):
        yield real_target


def is_codegen(target):
  """Returns True if the target is a codegen target."""
  return target.has_label('codegen')


def is_synthetic(target):
  """Returns True if the target is a synthetic target injected by the runtime."""
  return target.has_label('synthetic')


def is_jar_library(target):
  """Returns True if the target is an external jar library."""
  return target.has_label('jars')


def is_java(target):
  """Returns True if the target has or generates java sources."""
  return target.has_label('java')


def is_jvm_app(target):
  """Returns True if the target produces a java application with bundled auxiliary files."""
  return isinstance(target, JvmApp)


def is_thrift(target):
  """Returns True if the target has thrift IDL sources."""
  return isinstance(target, JavaThriftLibrary)


def is_apt(target):
  """Returns True if the target exports an annotation processor."""
  return target.has_label('apt')


def is_python(target):
  """Returns True if the target has python sources."""
  return target.has_label('python')


def is_scala(target):
  """Returns True if the target has scala sources."""
  return target.has_label('scala')


def is_scalac_plugin(target):
  """Returns True if the target builds a scalac plugin."""
  return target.has_label('scalac_plugin')


def is_test(t):
  """Returns True if the target is comprised of tests."""
  return t.has_label('tests')


def is_jar_dependency(dep):
  """Returns True if the dependency is an external jar."""
  return isinstance(dep, JarDependency)


def maven_layout():
  """Sets up typical maven project source roots for all built-in pants target types."""

  source_root('src/main/antlr', java_antlr_library, page, python_antlr_library)
  source_root('src/main/java', annotation_processor, java_library, jvm_binary, page)
  source_root('src/main/protobuf', java_protobuf_library, page)
  source_root('src/main/python', page, python_binary, python_library)
  source_root('src/main/resources', page, resources)
  source_root('src/main/scala', jvm_binary, page, scala_library)
  source_root('src/main/thrift', java_thrift_library, page, python_thrift_library)

  source_root('src/test/java', java_library, junit_tests, page)
  source_root('src/test/python', page, python_library, python_tests, python_test_suite)
  source_root('src/test/resources', page, resources)
  source_root('src/test/scala', junit_tests, page, scala_library, scala_specs)


def is_jar_dependency(dep):
  """Returns True if the dependency is an external jar."""
  return isinstance(dep, JarDependency)


# bind this as late as possible
pants = fancy_pants

# bind tasks and goals below utility functions they use from above
from twitter.pants.base import Config
from twitter.pants.goal import Context, Goal, Group, Phase
from twitter.pants.tasks import Task, TaskError

goal = Goal
group = Group
phase = Phase


# TODO(John Sirois): Update to dynamic linking when http://jira.local.twitter.com/browse/AWESOME-243
# is avaiable.
# bind twitter-specific idl helper
from twitter.pants.tasks.extract import Extract

compiled_idl = Extract.compiled_idl


__all__ = (
  'annotation_processor',
  'artifact',
  'benchmark',
  'bundle',
  'compiled_idl',
  'credentials',
  'dependencies',
  'exclude',
  'egg',
  'get_buildroot',
  'get_scm',
  'get_version',
  'globs',
  'goal',
  'group',
  'is_apt',
  'is_codegen',
  'is_exported',
  'is_internal',
  'is_jar_library',
  'is_jar',
  'is_jar_library',
  'is_java',
  'is_jvm',
  'is_python',
  'is_scala',
  'is_synthetic',
  'is_test',
  'jar',
  'jar_library',
  'java_antlr_library',
  'java_library',
  'java_protobuf_library',
  'java_tests',
  'java_thrift_library',
  'java_thriftstore_dml_library',
  'junit_tests',
  'jvm_app',
  'jvm_binary',
  'maven_layout',
  'oink_query',
  'page',
  'pants',
  'phase',
  'python_antlr_library',
  'python_artifact',
  'python_binary',
  'python_library',
  'python_requirement',
  'python_tests',
  'python_test_suite',
  'python_thrift_library',
  'repo',
  'resources',
  'rglobs',
  'scala_library',
  'scala_specs',
  'scala_tests',
  'scalac_plugin',
  'setup_py',
  'source_root',
  'wiki',
  'Config',
  'Context',
  'JavaLibrary',
  'JavaTests',
  'Task',
  'TaskError',
)
