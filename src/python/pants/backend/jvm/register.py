# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.group_task import GroupTask
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
from pants.backend.jvm.targets.jvm_binary import (
    Bundle,
    Duplicate,
    JvmApp,
    JvmBinary,
    JarRules,
    Skip)
from pants.backend.jvm.targets.repository import Repository
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.scala_tests import ScalaTests
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.backend.jvm.tasks.dependencies import Dependencies
from pants.backend.jvm.tasks.depmap import Depmap
from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.backend.jvm.tasks.eclipse_gen import EclipseGen
from pants.backend.jvm.tasks.filedeps import FileDeps
from pants.backend.jvm.tasks.idea_gen import IdeaGen
from pants.backend.jvm.tasks.ivy_imports import IvyImports
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
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal as goal
from pants.goal.phase import Phase


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
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
    },
    objects={
      'artifact': Artifact,
      'Duplicate': Duplicate,
      'exclude': Exclude,
      'jar': JarDependency,
      'jar_rules': JarRules,
      'Skip': Skip,
    },
    context_aware_object_factories={
      'bundle': Bundle.factory,
    }
  )


def register_goals():
  ng_killall = goal(name='ng-killall', action=NailgunKillall)
  ng_killall.install().with_description('Kill running nailgun servers.')

  Phase('invalidate').install(ng_killall, first=True)
  Phase('clean-all').install(ng_killall, first=True)
  Phase('clean-all-async').install(ng_killall, first=True)

  goal(name='bootstrap-jvm-tools', action=BootstrapJvmTools
  ).install('bootstrap').with_description('Bootstrap tools needed for building.')

  # Dependency resolution.
  goal(name='ivy', action=IvyResolve,
       dependencies=['gen', 'check-exclusives', 'bootstrap']
  ).install('resolve').with_description('Resolve dependencies and produce dependency reports.')

  goal(name='ivy-imports', action=IvyImports,
       dependencies=['bootstrap']
  ).install('imports')

  # Compilation.

  # AnnotationProcessors are java targets, but we need to force them into their own compilation
  # rounds so that they are on classpath of any dependees downstream that may use them. Without
  # forcing a separate member type we could get a java chunk containing a mix of apt processors and
  # code that relied on the un-compiled apt processor in the same javac invocation.  If so, javac
  # would not be smart enough to compile the apt processors 1st and activate them.
  class AptCompile(JavaCompile):
    @classmethod
    def name(cls):
      return 'apt'

    def select(self, target):
      return super(AptCompile, self).select(target) and target.is_apt


  jvm_compile = GroupTask.named(
    'jvm-compilers',
    product_type=['classes_by_target', 'classes_by_source'],
    flag_namespace=['compile'])

  # Here we register the ScalaCompile group member before the java group members very deliberately.
  # At some point ScalaLibrary targets will be able to own mixed scala and java source sets. At that
  # point, the ScalaCompile group member will still only select targets via has_sources('*.scala');
  # however if the JavaCompile group member were registered earlier, it would claim the ScalaLibrary
  # targets with mixed source sets leaving those targets un-compiled by scalac and resulting in
  # systemic compile errors.
  jvm_compile.add_member(ScalaCompile)

  # Its important we add AptCompile before JavaCompile since it 1st selector wins and apt code is a
  # subset of java code
  jvm_compile.add_member(AptCompile)

  jvm_compile.add_member(JavaCompile)

  goal(name='jvm', action=jvm_compile,
       dependencies=['gen', 'resolve', 'check-exclusives', 'bootstrap']
  ).install('compile').with_description('Compile source code.')

  # Generate documentation.

  goal(name='javadoc', action=JavadocGen,
       dependencies=['compile', 'bootstrap']
  ).install('doc').with_description('Create documentation.')

  goal(name='scaladoc', action=ScaladocGen,
       dependencies=['compile', 'bootstrap']
  ).install('doc')

  # Bundling.

  goal(name='jar', action=JarCreate,
       dependencies=['compile', 'resources', 'bootstrap']
  ).install('jar')

  detect_duplicates = goal(name='dup', action=DuplicateDetector,
                           dependencies=['compile', 'resources'])

  goal(name='binary', action=BinaryCreate,
       dependencies=['compile', 'resources', 'bootstrap']
  ).install().with_description('Create a jvm binary jar.')

  detect_duplicates.install('binary')

  goal(name='bundle', action=BundleCreate,
       dependencies=['compile', 'resources', 'bootstrap']
  ).install().with_description('Create an application bundle from binary targets.')

  detect_duplicates.install('bundle')

  goal(name='detect-duplicates', action=DuplicateDetector,
       dependencies=['compile', 'resources'],
  ).install().with_description('Detect duplicate classes and resources on the classpath.')

 # Publishing.

  goal(name='check_published_deps', action=CheckPublishedDeps
  ).install('check_published_deps').with_description('Find references to outdated artifacts.')

  goal(name='publish', action=JarPublish,
       dependencies=['jar', 'doc']
  ).install('publish').with_description('Publish artifacts.')

  # Testing.

  goal(name='junit', action=JUnitRun,
       dependencies=['compile', 'resources', 'bootstrap']
  ).install('test').with_description('Test compiled code.')

  goal(name='specs', action=SpecsRun,
       dependencies=['compile', 'resources', 'bootstrap']
  ).install('test')

  goal(name='bench', action=BenchmarkRun,
       dependencies=['compile', 'resources', 'bootstrap']
  ).install('bench')

  # Running.

  goal(name='jvm-run', action=JvmRun,
       dependencies=['compile', 'resources', 'bootstrap'], serialize=False
  ).install('run').with_description('Run a binary target.')

  goal(name='jvm-run-dirty', action=JvmRun,
       serialize=False
  ).install('run-dirty').with_description('Run a binary target, skipping compilation.')

  goal(name='scala-repl', action=ScalaRepl,
       dependencies=['compile', 'resources', 'bootstrap'], serialize=False
  ).install('repl').with_description('Run a REPL.')

  goal(name='scala-repl-dirty', action=ScalaRepl,
       serialize=False
  ).install('repl-dirty').with_description('Run a REPL, skipping compilation.')

  # IDE support.

  goal(name='idea', action=IdeaGen, dependencies=['bootstrap', 'resolve']
  ).install().with_description('Create an IntelliJ IDEA project from the given targets.')

  goal(name='eclipse', action=EclipseGen,
       dependencies=['jar', 'bootstrap']
  ).install().with_description('Create an Eclipse project from the given targets.')

  # Build graph information.

  goal(name='provides', action=Provides,
       dependencies=['jar', 'bootstrap']
  ).install().with_description('Print the symbols provided by the given targets.')

  # XXX(pl): These should be core, but they have dependencies on JVM
  goal(name='depmap', action=Depmap
  ).install().with_description("Depict the target's dependencies.")

  goal(name='dependencies', action=Dependencies
  ).install().with_description("Print the target's dependencies.")

  goal(name='filedeps', action=FileDeps
  ).install('filedeps').with_description(
      'Print out the source and BUILD files the target depends on.')
