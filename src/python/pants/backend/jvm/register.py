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
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagementSetup
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.shader import Shading
from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.benchmark import Benchmark
from pants.backend.jvm.targets.credentials import LiteralCredentials, NetrcCredentials
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_agent import JavaAgent
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.javac_plugin import JavacPlugin
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_app import Bundle, DirectoryReMapper, JvmApp
from pants.backend.jvm.targets.jvm_binary import Duplicate, JarRules, JvmBinary, Skip
from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand
from pants.backend.jvm.targets.managed_jar_dependencies import (ManagedJarDependencies,
                                                                ManagedJarLibraries)
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.backend.jvm.tasks.classmap import ClassmapTask
from pants.backend.jvm.tasks.consolidate_classpath import ConsolidateClasspath
from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.backend.jvm.tasks.ivy_imports import IvyImports
from pants.backend.jvm.tasks.ivy_outdated import IvyOutdated
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
from pants.backend.jvm.tasks.provide_tools_jar import ProvideToolsJar
from pants.backend.jvm.tasks.run_jvm_prep_command import (RunBinaryJvmPrepCommand,
                                                          RunCompileJvmPrepCommand,
                                                          RunTestJvmPrepCommand)
from pants.backend.jvm.tasks.scala_repl import ScalaRepl
from pants.backend.jvm.tasks.scaladoc_gen import ScaladocGen
from pants.backend.jvm.tasks.scalafmt import ScalaFmtCheckFormat, ScalaFmtFormat
from pants.backend.jvm.tasks.scalastyle import Scalastyle
from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.base.deprecated import warn_or_error
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependencyParseContextWrapper


class DeprecatedJavaTests(JUnitTests):
  def __init__(self, *args, **kwargs):
    super(DeprecatedJavaTests, self).__init__(*args, **kwargs)
    warn_or_error('1.4.0.dev0',
                  'java_tests(...) target type',
                  'Use junit_tests(...) instead for target {}.'.format(self.address.spec))


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'annotation_processor': AnnotationProcessor,
      'benchmark': Benchmark,
      'credentials': LiteralCredentials,
      'jar_library': JarLibrary,
      'java_agent': JavaAgent,
      'java_library': JavaLibrary,
      'javac_plugin': JavacPlugin,
      'java_tests': DeprecatedJavaTests,
      'junit_tests': JUnitTests,
      'jvm_app': JvmApp,
      'jvm_binary': JvmBinary,
      'jvm_prep_command' : JvmPrepCommand,
      'managed_jar_dependencies' : ManagedJarDependencies,
      'netrc_credentials': NetrcCredentials,
      'scala_library': ScalaLibrary,
      'scalac_plugin': ScalacPlugin,
      'unpacked_jars': UnpackedJars,
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
      'scala_jar': ScalaJarDependency,
      'jar_rules': JarRules,
      'repository': repo,
      'Skip': Skip,
      'shading_relocate': Shading.create_relocate,
      'shading_exclude': Shading.create_exclude,
      'shading_keep': Shading.create_keep,
      'shading_zap': Shading.create_zap,
      'shading_relocate_package': Shading.create_relocate_package,
      'shading_exclude_package': Shading.create_exclude_package,
      'shading_keep_package': Shading.create_keep_package,
      'shading_zap_package': Shading.create_zap_package,
    },
    context_aware_object_factories={
      'bundle': Bundle,
      'jar': JarDependencyParseContextWrapper,
      'managed_jar_libraries': ManagedJarLibraries,
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

  task(name='jar-dependency-management', action=JarDependencyManagementSetup).install('bootstrap')

  task(name='jvm-platform-explain', action=JvmPlatformExplain).install('jvm-platform-explain')
  task(name='jvm-platform-validate', action=JvmPlatformValidate).install('jvm-platform-validate')

  task(name='bootstrap-jvm-tools', action=BootstrapJvmTools).install('bootstrap')
  task(name='provide-tools-jar', action=ProvideToolsJar).install('bootstrap')

  # Compile
  task(name='zinc', action=ZincCompile).install('compile')

  # Dependency resolution.
  task(name='ivy', action=IvyResolve).install('resolve', first=True)
  task(name='ivy-imports', action=IvyImports).install('imports')
  task(name='unpack-jars', action=UnpackJars).install()
  task(name='ivy', action=IvyOutdated).install('outdated')

  # Resource preparation.
  task(name='prepare', action=PrepareResources).install('resources')
  task(name='services', action=PrepareServices).install('resources')

  task(name='export-classpath', action=RuntimeClasspathPublisher).install()
  task(name='jvm-dep-check', action=JvmDependencyCheck).install('compile')

  task(name='jvm', action=JvmDependencyUsage).install('dep-usage')

  task(name='classmap', action=ClassmapTask).install('classmap')

  # Generate documentation.
  task(name='javadoc', action=JavadocGen).install('doc')
  task(name='scaladoc', action=ScaladocGen).install('doc')

  # Bundling.
  task(name='create', action=JarCreate).install('jar')
  detect_duplicates = task(name='dup', action=DuplicateDetector)

  task(name='jvm', action=BinaryCreate).install('binary')
  detect_duplicates.install('binary')

  task(name='consolidate-classpath', action=ConsolidateClasspath).install('bundle')
  task(name='jvm', action=BundleCreate).install('bundle')
  detect_duplicates.install('bundle')

  task(name='detect-duplicates', action=DuplicateDetector).install()

  # Publishing.
  task(name='check-published-deps', action=CheckPublishedDeps).install('check-published-deps')

  task(name='jar', action=JarPublish).install('publish')

  # Testing.
  task(name='junit', action=JUnitRun).install('test')
  task(name='bench', action=BenchmarkRun).install('bench')

  # Linting.
  task(name='scalafmt', action=ScalaFmtCheckFormat, serialize=False).install('lint')
  task(name='scalastyle', action=Scalastyle, serialize=False).install('lint')
  task(name='checkstyle', action=Checkstyle, serialize=False).install('lint')

  # Running.
  task(name='jvm', action=JvmRun, serialize=False).install('run')
  task(name='jvm-dirty', action=JvmRun, serialize=False).install('run-dirty')
  task(name='scala', action=ScalaRepl, serialize=False).install('repl')
  task(name='scala-dirty', action=ScalaRepl, serialize=False).install('repl-dirty')
  task(name='scalafmt', action=ScalaFmtFormat, serialize=False).install('fmt')
  task(name='test-jvm-prep-command', action=RunTestJvmPrepCommand).install('test', first=True)
  task(name='binary-jvm-prep-command', action=RunBinaryJvmPrepCommand).install('binary', first=True)
  task(name='compile-jvm-prep-command', action=RunCompileJvmPrepCommand).install('compile', first=True)
