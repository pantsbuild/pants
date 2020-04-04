# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for both Java and Scala."""

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.ossrh_publication_metadata import (
    Developer,
    License,
    OSSRHPublicationMetadata,
    Scm,
)
from pants.backend.jvm.repository import Repository as repo
from pants.backend.jvm.rules.targets import (
    AnnotationProcessor,
    JarLibrary,
    JavaAgent,
    JavacPlugin,
    JavaLibrary,
    JunitTests,
    JvmApp,
    JvmBenchmark,
    JvmBinary,
    JvmCredentials,
    JvmPrepCommand,
    ManagedJarDependencies,
    NetrcCredentials,
    ScalacPlugin,
    ScalaLibrary,
    UnpackedJars,
)
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagementSetup
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.subsystems.shader import Shading
from pants.backend.jvm.targets.annotation_processor import (
    AnnotationProcessor as AnnotationProcessorV1,
)
from pants.backend.jvm.targets.benchmark import Benchmark as BenchmarkV1
from pants.backend.jvm.targets.credentials import LiteralCredentials as LiteralCredentialsV1
from pants.backend.jvm.targets.credentials import NetrcCredentials as NetrcCredentialsV1
from pants.backend.jvm.targets.jar_library import JarLibrary as JarLibraryV1
from pants.backend.jvm.targets.java_agent import JavaAgent as JavaAgentV1
from pants.backend.jvm.targets.java_library import JavaLibrary as JavaLibraryV1
from pants.backend.jvm.targets.javac_plugin import JavacPlugin as JavacPluginV1
from pants.backend.jvm.targets.junit_tests import JUnitTests as JUnitTestsV1
from pants.backend.jvm.targets.jvm_app import JvmApp as JvmAppV1
from pants.backend.jvm.targets.jvm_binary import Duplicate, JarRules
from pants.backend.jvm.targets.jvm_binary import JvmBinary as JvmBinaryV1
from pants.backend.jvm.targets.jvm_binary import Skip
from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand as JvmPrepCommandV1
from pants.backend.jvm.targets.managed_jar_dependencies import (
    ManagedJarDependencies as ManagedJarDependenciesV1,
)
from pants.backend.jvm.targets.managed_jar_dependencies import ManagedJarLibraries
from pants.backend.jvm.targets.scala_exclude import ScalaExclude
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.targets.scala_library import ScalaLibrary as ScalaLibraryV1
from pants.backend.jvm.targets.scalac_plugin import ScalacPlugin as ScalacPluginV1
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars as UnpackedJarsV1
from pants.backend.jvm.tasks.analysis_extraction import AnalysisExtraction
from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.backend.jvm.tasks.classmap import ClassmapTask
from pants.backend.jvm.tasks.consolidate_classpath import ConsolidateClasspath
from pants.backend.jvm.tasks.coursier_resolve import CoursierResolve
from pants.backend.jvm.tasks.detect_duplicates import DuplicateDetector
from pants.backend.jvm.tasks.ivy_imports import IvyImports
from pants.backend.jvm.tasks.ivy_outdated import IvyOutdated
from pants.backend.jvm.tasks.jar_create import JarCreate
from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.backend.jvm.tasks.javadoc_gen import JavadocGen
from pants.backend.jvm.tasks.junit_run import JUnitRun
from pants.backend.jvm.tasks.jvm_compile.javac.javac_compile import JavacCompile
from pants.backend.jvm.tasks.jvm_compile.jvm_classpath_publisher import RuntimeClasspathPublisher
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.backend.jvm.tasks.jvm_dependency_check import JvmDependencyCheck
from pants.backend.jvm.tasks.jvm_dependency_usage import JvmDependencyUsage
from pants.backend.jvm.tasks.jvm_platform_analysis import JvmPlatformExplain, JvmPlatformValidate
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.backend.jvm.tasks.nailgun_task import NailgunKillall
from pants.backend.jvm.tasks.prepare_resources import PrepareResources
from pants.backend.jvm.tasks.prepare_services import PrepareServices
from pants.backend.jvm.tasks.provide_tools_jar import ProvideToolsJar
from pants.backend.jvm.tasks.run_jvm_prep_command import (
    RunBinaryJvmPrepCommand,
    RunCompileJvmPrepCommand,
    RunTestJvmPrepCommand,
)
from pants.backend.jvm.tasks.scala_repl import ScalaRepl
from pants.backend.jvm.tasks.scaladoc_gen import ScaladocGen
from pants.backend.jvm.tasks.scalafix_task import ScalaFixCheck, ScalaFixFix
from pants.backend.jvm.tasks.scalafmt_task import ScalaFmtCheckFormat, ScalaFmtFormat
from pants.backend.jvm.tasks.scalastyle_task import ScalastyleTask
from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.backend.project_info.tasks.export_dep_as_jar import ExportDepAsJar
from pants.build_graph.app_base import Bundle, DirectoryReMapper
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependencyParseContextWrapper


def build_file_aliases():
    return BuildFileAliases(
        targets={
            "annotation_processor": AnnotationProcessorV1,
            "benchmark": BenchmarkV1,
            "credentials": LiteralCredentialsV1,
            "jar_library": JarLibraryV1,
            "java_agent": JavaAgentV1,
            "java_library": JavaLibraryV1,
            "javac_plugin": JavacPluginV1,
            "junit_tests": JUnitTestsV1,
            "jvm_app": JvmAppV1,
            "jvm_binary": JvmBinaryV1,
            "jvm_prep_command": JvmPrepCommandV1,
            "managed_jar_dependencies": ManagedJarDependenciesV1,
            "netrc_credentials": NetrcCredentialsV1,
            "scala_library": ScalaLibraryV1,
            "scalac_plugin": ScalacPluginV1,
            "unpacked_jars": UnpackedJarsV1,
        },
        objects={
            "artifact": Artifact,
            "scala_artifact": ScalaArtifact,
            "ossrh": OSSRHPublicationMetadata,
            "license": License,
            "scm": Scm,
            "developer": Developer,
            "github": Scm.github,
            "DirectoryReMapper": DirectoryReMapper,
            "Duplicate": Duplicate,
            "exclude": Exclude,
            "scala_jar": ScalaJarDependency,
            "scala_exclude": ScalaExclude,
            "jar_rules": JarRules,
            "repository": repo,
            "Skip": Skip,
            "shading_relocate": Shading.create_relocate,
            "shading_exclude": Shading.create_exclude,
            "shading_keep": Shading.create_keep,
            "shading_zap": Shading.create_zap,
            "shading_relocate_package": Shading.create_relocate_package,
            "shading_exclude_package": Shading.create_exclude_package,
            "shading_keep_package": Shading.create_keep_package,
            "shading_zap_package": Shading.create_zap_package,
        },
        context_aware_object_factories={
            "bundle": Bundle,
            "jar": JarDependencyParseContextWrapper,
            "managed_jar_libraries": ManagedJarLibraries,
        },
    )


def global_subsystems():
    return (
        ScalaPlatform,
        ScoveragePlatform,
    )


# TODO https://github.com/pantsbuild/pants/issues/604 register_goals
def register_goals():
    ng_killall = task(name="ng-killall", action=NailgunKillall)
    ng_killall.install()

    Goal.by_name("invalidate").install(ng_killall, first=True)
    Goal.by_name("clean-all").install(ng_killall, first=True)

    task(name="jar-dependency-management", action=JarDependencyManagementSetup).install("bootstrap")

    task(name="jvm-platform-explain", action=JvmPlatformExplain).install("jvm-platform-explain")
    task(name="jvm-platform-validate", action=JvmPlatformValidate).install("jvm-platform-validate")

    task(name="bootstrap-jvm-tools", action=BootstrapJvmTools).install("bootstrap")
    task(name="provide-tools-jar", action=ProvideToolsJar).install("bootstrap")

    # Compile
    task(name="rsc", action=RscCompile).install("compile")
    task(name="javac", action=JavacCompile).install("compile")

    # Analysis extraction.
    task(name="zinc", action=AnalysisExtraction).install("analysis")

    # Dependency resolution.
    task(name="coursier", action=CoursierResolve).install("resolve")
    task(name="ivy-imports", action=IvyImports).install("imports")
    task(name="unpack-jars", action=UnpackJars).install()
    task(name="ivy", action=IvyOutdated).install("outdated")

    # Resource preparation.
    task(name="prepare", action=PrepareResources).install("resources")
    task(name="services", action=PrepareServices).install("resources")

    task(name="export-classpath", action=RuntimeClasspathPublisher).install()

    # This goal affects the contents of the runtime_classpath, and should not be
    # combined with any other goals on the command line.
    task(name="export-dep-as-jar", action=ExportDepAsJar).install()

    task(name="jvm", action=JvmDependencyUsage).install("dep-usage")

    task(name="classmap", action=ClassmapTask).install("classmap")

    # Generate documentation.
    task(name="javadoc", action=JavadocGen).install("doc")
    task(name="scaladoc", action=ScaladocGen).install("doc")

    # Bundling.
    task(name="create", action=JarCreate).install("jar")
    detect_duplicates = task(name="dup", action=DuplicateDetector)

    task(name="jvm", action=BinaryCreate).install("binary")
    detect_duplicates.install("binary")

    task(name="consolidate-classpath", action=ConsolidateClasspath).install("bundle")
    task(name="jvm", action=BundleCreate).install("bundle")
    detect_duplicates.install("bundle")

    task(name="detect-duplicates", action=DuplicateDetector).install()

    # Publishing.
    task(name="check-published-deps", action=CheckPublishedDeps).install("check-published-deps")

    task(name="jar", action=JarPublish).install("publish")

    # Testing.
    task(name="junit", action=JUnitRun).install("test")
    task(name="bench", action=BenchmarkRun).install("bench")

    # Linting.
    task(name="scalafix", action=ScalaFixCheck).install("lint")
    task(name="scalafmt", action=ScalaFmtCheckFormat, serialize=False).install("lint")
    task(name="scalastyle", action=ScalastyleTask, serialize=False).install("lint")
    task(name="checkstyle", action=Checkstyle, serialize=False).install("lint")
    task(name="jvm-dep-check", action=JvmDependencyCheck, serialize=False).install("lint")

    # Formatting.
    # Scalafix has to go before scalafmt in order not to
    # further change Scala files after scalafmt.
    task(name="scalafix", action=ScalaFixFix).install("fmt")
    task(name="scalafmt", action=ScalaFmtFormat, serialize=False).install("fmt")

    # Running.
    task(name="jvm", action=JvmRun, serialize=False).install("run")
    task(name="jvm-dirty", action=JvmRun, serialize=False).install("run-dirty")
    task(name="scala", action=ScalaRepl, serialize=False).install("repl")
    task(name="scala-dirty", action=ScalaRepl, serialize=False).install("repl-dirty")
    task(name="test-jvm-prep-command", action=RunTestJvmPrepCommand).install("test", first=True)
    task(name="binary-jvm-prep-command", action=RunBinaryJvmPrepCommand).install(
        "binary", first=True
    )
    task(name="compile-jvm-prep-command", action=RunCompileJvmPrepCommand).install(
        "compile", first=True
    )


def targets2():
    return [
        AnnotationProcessor,
        JvmBenchmark,
        JvmCredentials,
        JarLibrary,
        JavaAgent,
        JavaLibrary,
        JavacPlugin,
        JunitTests,
        JvmApp,
        JvmBinary,
        JvmPrepCommand,
        ManagedJarDependencies,
        NetrcCredentials,
        ScalaLibrary,
        ScalacPlugin,
        UnpackedJars,
    ]
