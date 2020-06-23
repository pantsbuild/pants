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
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.subsystems.shader import Shading
from pants.backend.jvm.target_types import (
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
from pants.build_graph.app_base import DirectoryReMapper
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.bundle import Bundle
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


def target_types():
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
