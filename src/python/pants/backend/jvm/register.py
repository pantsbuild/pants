# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.group_task import GroupTask
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
from pants.backend.jvm.tasks.jvm_compile.java.java_compile import JmakeCompile
from pants.backend.jvm.tasks.jvm_compile.zinc.apt_compile import AptCompile
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.backend.jvm.tasks.jvm_dependency_check import JvmDependencyCheck
from pants.backend.jvm.tasks.jvm_dependency_usage import JvmDependencyUsage
from pants.backend.jvm.tasks.jvm_platform_analysis import JvmPlatformExplain, JvmPlatformValidate
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.backend.jvm.tasks.nailgun_task import NailgunKillall
from pants.backend.jvm.tasks.prepare_resources import PrepareResources
from pants.backend.jvm.tasks.prepare_services import PrepareServices
from pants.backend.jvm.tasks.scala_repl import ScalaRepl
from pants.backend.jvm.tasks.scaladoc_gen import ScaladocGen
from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.base.deprecated import deprecated
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task


@deprecated(removal_version='0.0.52', hint_message="Replace 'Repository' with 'repository'.")
def Repository(*args, **kwargs):
  return repo(*args, **kwargs)


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
      'Repository': Repository,
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
  ng_killall.install().with_description('Kill running nailgun servers.')

  Goal.by_name('invalidate').install(ng_killall, first=True)
  Goal.by_name('clean-all').install(ng_killall, first=True)
  Goal.by_name('clean-all-async').install(ng_killall, first=True)

  task(name='jvm-platform-explain', action=JvmPlatformExplain).install('jvm-platform-explain')
  task(name='jvm-platform-validate', action=JvmPlatformValidate).install('jvm-platform-validate')

  task(name='bootstrap-jvm-tools', action=BootstrapJvmTools).install('bootstrap').with_description(
      'Bootstrap tools needed for building.')

  # Dependency resolution.
  task(name='ivy', action=IvyResolve).install('resolve').with_description(
      'Resolve dependencies and produce dependency reports.')

  task(name='ivy-imports', action=IvyImports).install('imports')

  task(name='unpack-jars', action=UnpackJars).install().with_description(
    'Unpack artifacts specified by unpacked_jars() targets.')

  # Resource preparation.
  task(name='prepare', action=PrepareResources).install('resources')
  task(name='services', action=PrepareServices).install('resources')

  # Compilation.
  jvm_compile = GroupTask.named(
      'jvm-compilers',
      product_type=['classes_by_target', 'classes_by_source', 'resources_by_target', 'product_deps_by_src'],
      flag_namespace=['compile'])

  # It's important we add AptCompile before other java-compiling tasks since the first selector wins,
  # and apt code is a subset of java code.
  jvm_compile.add_member(AptCompile)
  jvm_compile.add_member(JmakeCompile)
  jvm_compile.add_member(ZincCompile)

  task(name='jvm', action=jvm_compile).install('compile').with_description('Compile source code.')
  task(name='jvm-dep-check', action=JvmDependencyCheck).install('compile').with_description(
      'Check that used dependencies have been requested.')

  task(name='jvm', action=JvmDependencyUsage).install('dep-usage').with_description(
      'Collect target dependency usage data.')

  # Generate documentation.
  task(name='javadoc', action=JavadocGen).install('doc').with_description('Create documentation.')
  task(name='scaladoc', action=ScaladocGen).install('doc')

  # Bundling.
  task(name='jar', action=JarCreate).install('jar')
  detect_duplicates = task(name='dup', action=DuplicateDetector)

  task(name='binary', action=BinaryCreate).install().with_description('Create a runnable binary.')
  detect_duplicates.install('binary')

  task(name='bundle', action=BundleCreate).install().with_description(
      'Create an application bundle from binary targets.')
  detect_duplicates.install('bundle')

  task(name='detect-duplicates', action=DuplicateDetector).install().with_description(
      'Detect duplicate classes and resources on the classpath.')

 # Publishing.
  task(
    name='check_published_deps',
    action=CheckPublishedDeps,
  ).install('check_published_deps').with_description('Find references to outdated artifacts.')

  task(name='jar', action=JarPublish).install('publish').with_description(
      'Publish artifacts.')

  # Testing.
  task(name='junit', action=JUnitRun).install('test').with_description('Test compiled code.')
  task(name='bench', action=BenchmarkRun).install('bench').with_description('Run benchmark tests.')

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
