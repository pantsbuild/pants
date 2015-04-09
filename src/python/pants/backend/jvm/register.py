# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.group_task import GroupTask
from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.benchmark import Benchmark
from pants.backend.jvm.targets.credentials import Credentials
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import IvyArtifact, JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_agent import JavaAgent
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_app import Bundle, DirectoryReMapper, JvmApp
from pants.backend.jvm.targets.jvm_binary import Duplicate, JarRules, JvmBinary, Skip
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.scala_tests import ScalaTests
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.backend.jvm.tasks.ivy_imports import IvyImports
from pants.backend.jvm.tasks.ivy_resolve import IvyResolve
from pants.backend.jvm.tasks.jar_create import JarCreate
from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.backend.jvm.tasks.javadoc_gen import JavadocGen
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.backend.jvm.tasks.jvm_compile.java.apt_compile import AptCompile
from pants.backend.jvm.tasks.jvm_compile.java.java_compile import JavaCompile
from pants.backend.jvm.tasks.jvm_compile.scala.scala_compile import ScalaCompile
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.backend.jvm.tasks.nailgun_task import NailgunKillall
from pants.backend.jvm.tasks.scala_repl import ScalaRepl
from pants.backend.jvm.tasks.scaladoc_gen import ScaladocGen
from pants.backend.jvm.tasks.specs_run import SpecsRun
from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'annotation_processor': AnnotationProcessor,
      'benchmark': Benchmark,
      'credentials': Credentials,
      'jar_library': JarLibrary,
      'unpacked_jars' : UnpackedJars,
      'java_agent': JavaAgent,
      'java_library': JavaLibrary,
      'java_tests': JavaTests,
      'junit_tests': JavaTests,
      'jvm_app': JvmApp,
      'jvm_binary': JvmBinary,
      'scala_library': ScalaLibrary,
      'scala_specs': ScalaTests,
      'scala_tests': ScalaTests,
      'scalac_plugin': ScalacPlugin,
    },
    objects={
      'artifact': Artifact,
      'DirectoryReMapper': DirectoryReMapper,
      'Duplicate': Duplicate,
      'exclude': Exclude,
      'ivy_artifact': IvyArtifact,
      'jar': JarDependency,
      'jar_rules': JarRules,
      'Repository': Repository,
      'Skip': Skip,
    },
    context_aware_object_factories={
      'bundle': Bundle.factory,
    }
  )


# TODO https://github.com/pantsbuild/pants/issues/604 register_goals
def register_goals():
  ng_killall = task(name='ng-killall', action=NailgunKillall)
  ng_killall.install().with_description('Kill running nailgun servers.')

  Goal.by_name('invalidate').install(ng_killall, first=True)
  Goal.by_name('clean-all').install(ng_killall, first=True)
  Goal.by_name('clean-all-async').install(ng_killall, first=True)

  task(name='bootstrap-jvm-tools', action=BootstrapJvmTools).install('bootstrap').with_description(
      'Bootstrap tools needed for building.')

  # Dependency resolution.
  task(name='ivy', action=IvyResolve).install('resolve').with_description(
      'Resolve dependencies and produce dependency reports.')

  task(name='ivy-imports', action=IvyImports).install('imports')

  task(name='unpack-jars', action=UnpackJars).install().with_description(
    'Unpack artifacts specified by unpacked_jars() targets.')

  # Compilation.

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

  task(name='jvm', action=jvm_compile).install('compile').with_description('Compile source code.')

  # Generate documentation.
  task(name='javadoc', action=JavadocGen).install('doc').with_description('Create documentation.')
  task(name='scaladoc', action=ScaladocGen).install('doc')

  # Bundling.
  task(name='jar', action=JarCreate).install('jar')

  task(name='binary', action=BinaryCreate).install().with_description('Create a runnable binary.')

  task(name='bundle', action=BundleCreate).install().with_description(
      'Create an application bundle from binary targets.')

  # Install the duplicate detector as an independent goal, and under the binary goal.
  task(name='dup', action=DuplicateDetector).install('binary')
  task(name='detect-duplicates', action=DuplicateDetector).install().with_description(
      'Detect duplicate classes and resources on the classpath.')

 # Publishing.
  task(
    name='check_published_deps',
    action=CheckPublishedDeps,
  ).install('check_published_deps').with_description('Find references to outdated artifacts.')

  task(name='publish', action=JarPublish).install('publish').with_description(
      'Publish artifacts.')

  # Testing.
  task(name='junit', action=JUnitRun).install('test').with_description('Test compiled code.')
  task(name='specs', action=SpecsRun).install('test')
  task(name='bench', action=BenchmarkRun).install('bench')

  # Running.
  task(name='jvm', action=JvmRun, serialize=False).install('run').with_description(
      'Run a binary target.')
  task(name='jvm-dirty', action=JvmRun, serialize=False).install('run-dirty').with_description(
      'Run a binary target, skipping compilation.')

  task(name='scala', action=ScalaRepl, serialize=False).install('repl').with_description(
      'Run a REPL.')
  task(
    name='scala-dirty',
    action=ScalaRepl,
    serialize=False
  ).install('repl-dirty').with_description('Run a REPL, skipping compilation.')
