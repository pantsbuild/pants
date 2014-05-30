# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.goal import Goal as goal, Group as group

from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.artifact import Artifact
from pants.backend.jvm.targets.benchmark import Benchmark
from pants.backend.jvm.targets.credentials import Credentials
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_agent import JavaAgent
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_binary import Bundle, JvmApp, JvmBinary
from pants.backend.jvm.targets.repository import Repository
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.scala_tests import ScalaTests
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.backend.jvm.tasks.dependencies import Dependencies
from pants.backend.jvm.tasks.depmap import Depmap
from pants.backend.jvm.tasks.filedeps import FileDeps
from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.backend.jvm.tasks.eclipse_gen import EclipseGen
from pants.backend.jvm.tasks.idea_gen import IdeaGen
from pants.backend.jvm.tasks.ivy_resolve import IvyResolve
from pants.backend.jvm.tasks.jar_create import JarCreate
from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.backend.jvm.tasks.javadoc_gen import JavadocGen
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.backend.jvm.tasks.jvm_compile.java.java_compile import JavaCompile
from pants.backend.jvm.tasks.jvm_compile.scala.scala_compile import ScalaCompile
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.backend.jvm.tasks.nailgun_task import NailgunKillall
from pants.backend.jvm.tasks.provides import Provides
from pants.backend.jvm.tasks.scala_repl import ScalaRepl
from pants.backend.jvm.tasks.scaladoc_gen import ScaladocGen
from pants.backend.jvm.tasks.specs_run import SpecsRun


def target_aliases():
  return {
    'annotation_processor': AnnotationProcessor,
    'benchmark': Benchmark,
    'credentials': Credentials,
    'jar_library': JarLibrary,
    'java_agent': JavaAgent,
    'java_library': JavaLibrary,
    'java_tests': JavaTests,
    'junit_tests': JavaTests,
    'jvm_app': JvmApp,
    'jvm_binary': JvmBinary,
    'repo': Repository,
    'scala_library': ScalaLibrary,
    'scala_specs': ScalaTests,
    'scala_tests': ScalaTests,
    'scalac_plugin': ScalacPlugin,
  }


def object_aliases():
  return {
    'artifact': Artifact,
    'jar': JarDependency,
    'exclude': Exclude,
  }

def partial_path_relative_util_aliases():
  return {
    'bundle': Bundle,
  }


def applicative_path_relative_util_aliases():
  return {}


def register_commands():
  pass


def register_goals():
  goal(name='ng-killall', action=NailgunKillall
  ).install().with_description('Kill running nailgun servers.')


  goal(name='bootstrap-jvm-tools', action=BootstrapJvmTools
  ).install('bootstrap').with_description('Bootstrap tools needed for building.')

  # Dependency resolution.
  goal(name='ivy', action=IvyResolve, dependencies=['gen', 'check-exclusives', 'bootstrap']
  ).install('resolve').with_description('Resolve dependencies and produce dependency reports.')

  # Compilation.

  # When chunking a group, we don't need a new chunk for targets with no sources at all
  # (which do sometimes exist, e.g., when creating a BUILD file ahead of its code).
  def _has_sources(target, extension):
    return target.has_sources(extension) or target.has_label('sources') and not target.sources

  # Note: codegen targets shouldn't really be 'is_java' or 'is_scala', but right now they
  # are so they don't cause a lot of islands while chunking. The jvm group doesn't act on them
  # anyway (it acts on their synthetic counterparts) so it doesn't matter where they get chunked.
  # TODO: Make chunking only take into account the targets actually acted on? This would require
  # task types to declare formally the targets they act on.
  def _is_java(target):
    return (target.is_java or
            (isinstance(target, (JvmBinary, JavaTests, Benchmark))
             and _has_sources(target, '.java'))) and not target.is_apt

  def _is_scala(target):
    return (target.is_scala or
            (isinstance(target, (JvmBinary, JavaTests, Benchmark))
             and _has_sources(target, '.scala')))


  class AptCompile(JavaCompile): pass  # So they're distinct in log messages etc.

  jvm_compile_deps = ['gen', 'resolve', 'check-exclusives', 'bootstrap']

  goal(name='apt', action=AptCompile, group=group('jvm', lambda t: t.is_apt), dependencies=jvm_compile_deps
  ).install('compile')

  goal(name='java', action=JavaCompile, group=group('jvm', _is_java), dependencies=jvm_compile_deps
  ).install('compile')

  goal(name='scala', action=ScalaCompile, group=group('jvm', _is_scala), dependencies=jvm_compile_deps
  ).install('compile').with_description('Compile source code.')

  # Generate documentation.

  class ScaladocJarShim(ScaladocGen):
    def __init__(self, context, workdir, confs=None):
      super(ScaladocJarShim, self).__init__(context, workdir, confs=confs, active=False)

  class JavadocJarShim(JavadocGen):
    def __init__(self, context, workdir, confs=None):
      super(JavadocJarShim, self).__init__(context, workdir, confs=confs, active=False)

  goal(name='javadoc', action=JavadocGen, dependencies=['compile', 'bootstrap']
  ).install('doc').with_description('Create documentation.')

  goal(name='scaladoc', action=ScaladocGen, dependencies=['compile', 'bootstrap']
  ).install('doc')

  goal(name='javadoc_publish', action=JavadocJarShim
  ).install('publish')

  goal(name='scaladoc_publish', action=ScaladocJarShim
  ).install('publish')


  # Bundling and publishing.

  goal(name='jar', action=JarCreate, dependencies=['compile', 'resources', 'bootstrap']
  ).install('jar')

  goal(name='binary', action=BinaryCreate, dependencies=['jar', 'bootstrap']
  ).install().with_description('Create a jvm binary jar.')

  goal(name='bundle', action=BundleCreate, dependencies=['jar', 'bootstrap', 'binary']
  ).install().with_description('Create an application bundle from binary targets.')

  goal(name='check_published_deps', action=CheckPublishedDeps
  ).install('check_published_deps').with_description('Find references to outdated artifacts.')

  goal(name='jar_create_publish', action=JarCreate, dependencies=['compile', 'resources']
  ).install('publish')

  goal(name='publish', action=JarPublish
  ).install('publish').with_description('Publish artifacts.')

  goal(name='dup',action=DuplicateDetector,
  ).install('binary')

  goal(name='detect-duplicates', action=DuplicateDetector, dependencies=['jar']
  ).install().with_description('Detect duplicate classes and resources on the classpath.')

  # Testing.

  goal(name='junit', action=JUnitRun, dependencies=['compile', 'resources', 'bootstrap']
  ).install('test').with_description('Test compiled code.')

  goal(name='specs', action=SpecsRun, dependencies=['compile', 'resources', 'bootstrap']
  ).install('test')

  goal(name='bench', action=BenchmarkRun, dependencies=['compile', 'resources', 'bootstrap']
  ).install('bench')


  # Running.

  goal(name='jvm-run', action=JvmRun, dependencies=['compile', 'resources', 'bootstrap'], serialize=False
  ).install('run').with_description('Run a (currently JVM only) binary target.')

  goal(name='jvm-run-dirty', action=JvmRun, serialize=False
  ).install('run-dirty').with_description('Run a (currently JVM only) binary target, skipping compilation.')

  goal(name='scala-repl', action=ScalaRepl, dependencies=['compile', 'resources', 'bootstrap'], serialize=False
  ).install('repl').with_description('Run a (currently Scala only) REPL.')

  goal(name='scala-repl-dirty', action=ScalaRepl, serialize=False
  ).install('repl-dirty').with_description('Run a (currently Scala only) REPL, skipping compilation.')

  # IDE support.

  goal(name='idea', action=IdeaGen, dependencies=['jar', 'bootstrap']
  ).install().with_description('Create an IntelliJ IDEA project from the given targets.')

  goal(name='eclipse', action=EclipseGen, dependencies=['jar', 'bootstrap']
  ).install().with_description('Create an Eclipse project from the given targets.')


  # Build graph information.

  goal(name='provides', action=Provides, dependencies=['jar', 'bootstrap']
  ).install().with_description('Print the symbols provided by the given targets.')

  # XXX(pl): These should be core, but they have dependencies on JVM
  goal(name='depmap', action=Depmap
  ).install().with_description("Depict the target's dependencies.")

  goal(name='dependencies', action=Dependencies
  ).install().with_description("Print the target's dependencies.")

  goal(name='filedeps', action=FileDeps
  ).install('filedeps').with_description('Print out the source and BUILD files the target depends on.')

