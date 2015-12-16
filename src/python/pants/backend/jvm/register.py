# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.ossrh_publication_metadata import (Developer, License,
                                                          OSSRHPublicationMetadata, Scm)
from pants.backend.jvm.repository import Repository as repo
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.shader import Shading
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.benchmark import Benchmark
from pants.backend.jvm.targets.credentials import Credentials
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_agent import JavaAgent
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_app import Bundle, DirectoryReMapper, JvmApp
from pants.backend.jvm.targets.jvm_binary import Duplicate, JarRules, JvmBinary, Skip
from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.targets.scala_library import ScalaLibrary
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
from pants.backend.jvm.tasks.jvm_compile.jvm_classpath_publisher import RuntimeClasspathPublisher
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.backend.jvm.tasks.jvm_dependency_check import JvmDependencyCheck
from pants.backend.jvm.tasks.jvm_dependency_usage import JvmDependencyUsage
from pants.backend.jvm.tasks.jvm_platform_analysis import JvmPlatformExplain, JvmPlatformValidate
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.backend.jvm.tasks.nailgun_task import NailgunKillall
from pants.backend.jvm.tasks.prepare_resources import PrepareResources
from pants.backend.jvm.tasks.prepare_services import PrepareServices
from pants.backend.jvm.tasks.run_jvm_prep_command import (RunBinaryJvmPrepCommand,
                                                          RunCompileJvmPrepCommand,
                                                          RunTestJvmPrepCommand)
from pants.backend.jvm.tasks.scala_repl import ScalaRepl
from pants.backend.jvm.tasks.scaladoc_gen import ScaladocGen
from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'annotation_processor': AnnotationProcessor,
      'benchmark': Benchmark,
      'credentials': Credentials,
      'jar_library': JarLibrary,
      'unpacked_jars': UnpackedJars,
      'java_agent': JavaAgent,
      'java_library': JavaLibrary,
      'java_tests': JavaTests,
      'junit_tests': JavaTests,
      'jvm_app': JvmApp,
      'jvm_binary': JvmBinary,
      'jvm_prep_command' : JvmPrepCommand,
      'scala_library': ScalaLibrary,
      'scalac_plugin': ScalacPlugin,
    },
    objects={
      'artifact': Artifact,
      'scala_artifact': ScalaArtifact,
      'ossrh': OSSRHPublicationMetadata,
      'license': License,
      'scm': Scm,
      'developer': Developer,
      'github': Scm.github,
      'DirectoryReMapper': DirectoryReMapper,
      'Duplicate': Duplicate,
      'exclude': Exclude,
      'jar': JarDependency,
      'scala_jar': ScalaJarDependency,
      'jar_rules': JarRules,
      'repository': repo,
      'Skip': Skip,
      'shading_relocate': Shading.Relocate.new,
      'shading_exclude': Shading.Exclude.new,
      'shading_relocate_package': Shading.RelocatePackage.new,
      'shading_exclude_package': Shading.ExcludePackage.new,
    },
    context_aware_object_factories={
      'bundle': Bundle.factory,
    }
  )


def global_subsystems():
  return (ScalaPlatform,)


# TODO https://github.com/pantsbuild/pants/issues/604 register_goals
def register_goals():
  ng_killall = task(name='ng-killall', action=NailgunKillall)
  ng_killall.install()

  Goal.by_name('invalidate').install(ng_killall, first=True)
  Goal.by_name('clean-all').install(ng_killall, first=True)

  task(name='jvm-platform-explain', action=JvmPlatformExplain).install('jvm-platform-explain')
  task(name='jvm-platform-validate', action=JvmPlatformValidate).install('jvm-platform-validate')

  task(name='bootstrap-jvm-tools', action=BootstrapJvmTools).install('bootstrap')

  # Compile
  task(name='zinc', action=ZincCompile).install('compile')

  # Dependency resolution.
  task(name='ivy', action=IvyResolve).install('resolve')
  task(name='ivy-imports', action=IvyImports).install('imports')
  task(name='unpack-jars', action=UnpackJars).install()

  # Resource preparation.
  task(name='prepare', action=PrepareResources).install('resources')
  task(name='services', action=PrepareServices).install('resources')

  task(name='export-classpath', action=RuntimeClasspathPublisher).install()
  task(name='jvm-dep-check', action=JvmDependencyCheck).install('compile')

  task(name='jvm', action=JvmDependencyUsage).install('dep-usage')

  # Generate documentation.
  task(name='javadoc', action=JavadocGen).install('doc')
  task(name='scaladoc', action=ScaladocGen).install('doc')

  # Bundling.
  Goal.register('jar', 'Create a JAR file.')
  task(name='create', action=JarCreate).install('jar')
  detect_duplicates = task(name='dup', action=DuplicateDetector)

  task(name='jvm', action=BinaryCreate).install('binary')
  detect_duplicates.install('binary')

  task(name='jvm', action=BundleCreate).install('bundle')
  detect_duplicates.install('bundle')

  task(name='detect-duplicates', action=DuplicateDetector).install()

  # Publishing.
  task(
    name='check_published_deps',
    action=CheckPublishedDeps,
  ).install('check_published_deps')

  task(name='jar', action=JarPublish).install('publish')

  # Testing.
  task(name='junit', action=JUnitRun).install('test')
  task(name='bench', action=BenchmarkRun).install('bench')

  # Running.
  task(name='jvm', action=JvmRun, serialize=False).install('run')
  task(name='jvm-dirty', action=JvmRun, serialize=False).install('run-dirty')
  task(name='scala', action=ScalaRepl, serialize=False).install('repl')
  task(name='scala-dirty', action=ScalaRepl, serialize=False).install('repl-dirty')
  task(name='test-jvm-prep-command', action=RunTestJvmPrepCommand).install('test', first=True)
  task(name='binary-jvm-prep-command', action=RunBinaryJvmPrepCommand).install('binary', first=True)
  task(name='compile-jvm-prep-command', action=RunCompileJvmPrepCommand).install('compile', first=True)
