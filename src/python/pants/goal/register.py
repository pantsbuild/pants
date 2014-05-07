# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.goal import Goal as goal, Group as group
from pants.targets.benchmark import Benchmark
from pants.targets.java_tests import JavaTests
from pants.targets.jvm_binary import JvmBinary
from pants.tasks.antlr_gen import AntlrGen
from pants.tasks.apache_thrift_gen import ApacheThriftGen
from pants.tasks.benchmark_run import BenchmarkRun
from pants.tasks.binary_create import BinaryCreate
from pants.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.tasks.build_lint import BuildLint
from pants.tasks.builddictionary import BuildBuildDictionary
from pants.tasks.bundle_create import BundleCreate
from pants.tasks.check_exclusives import CheckExclusives
from pants.tasks.check_published_deps import CheckPublishedDeps
from pants.tasks.checkstyle import Checkstyle
from pants.tasks.clean import Invalidator, Cleaner, AsyncCleaner
from pants.tasks.dependees import ReverseDepmap
from pants.tasks.depmap import Depmap
from pants.tasks.dependencies import Dependencies
from pants.tasks.detect_duplicates import DuplicateDetector
from pants.tasks.eclipse_gen import EclipseGen
from pants.tasks.filedeps import FileDeps
from pants.tasks.filemap import Filemap
from pants.tasks.filter import Filter
from pants.tasks.idea_gen import IdeaGen
from pants.tasks.ivy_resolve import IvyResolve
from pants.tasks.jar_create import JarCreate
from pants.tasks.jar_publish import JarPublish
from pants.tasks.javadoc_gen import JavadocGen
from pants.tasks.junit_run import JUnitRun
from pants.tasks.jvm_compile.java.java_compile import JavaCompile
from pants.tasks.jvm_compile.scala.scala_compile import ScalaCompile
from pants.tasks.jvm_run import JvmRun
from pants.tasks.list_goals import ListGoals
from pants.tasks.listtargets import ListTargets
from pants.tasks.markdown_to_html import MarkdownToHtml
from pants.tasks.minimal_cover import MinimalCover
from pants.tasks.nailgun_task import NailgunKillall
from pants.tasks.paths import Path, Paths
from pants.tasks.pathdeps import PathDeps
from pants.tasks.prepare_resources import PrepareResources
from pants.tasks.protobuf_gen import ProtobufGen
from pants.tasks.provides import Provides
from pants.tasks.python.setup import SetupPythonEnvironment
from pants.tasks.reporting_server import RunServer, KillServer
from pants.tasks.roots import ListRoots
from pants.tasks.scala_repl import ScalaRepl
from pants.tasks.scaladoc_gen import ScaladocGen
from pants.tasks.scrooge_gen import ScroogeGen
from pants.tasks.sorttargets import SortTargets
from pants.tasks.specs_run import SpecsRun
from pants.tasks.targets_help import TargetsHelp


# Getting help.

goal(name='goals', action=ListGoals
).install().with_description('List all documented goals.')

goal(name='targets', action=TargetsHelp
).install().with_description('List all target types.')

goal(name='builddict', action=BuildBuildDictionary
).install()


# Cleaning.

goal(name='invalidate', action=Invalidator, dependencies=['ng-killall']
).install().with_description('Invalidate all targets.')

goal(name='clean-all', action=Cleaner, dependencies=['invalidate']
).install().with_description('Clean all build output.')

goal(name='clean-all-async', action=AsyncCleaner, dependencies=['invalidate']
).install().with_description('Clean all build output in a background process.')

goal(name='ng-killall', action=NailgunKillall
).install().with_description('Kill running nailgun servers.')


# Reporting.

goal(name='server', action=RunServer, serialize=False
).install().with_description('Run the pants reporting server.')

goal(name='killserver', action=KillServer, serialize=False
).install().with_description('Kill the reporting server.')


# Bootstrapping.

goal(name='bootstrap-jvm-tools', action=BootstrapJvmTools
).install('bootstrap').with_description('Bootstrap tools needed for building.')

# TODO(benjy): What is this? Do we need it?
goal(name='python-setup', action=SetupPythonEnvironment
).install('setup').with_description("Setup the target's build environment.")


# Dependency resolution.
goal(name='ivy', action=IvyResolve, dependencies=['gen', 'check-exclusives', 'bootstrap']
).install('resolve').with_description('Resolve dependencies and produce dependency reports.')


# Code generation.

goal(name='thrift', action=ApacheThriftGen
).install('gen').with_description('Generate code.')

goal(name='scrooge', dependencies=['bootstrap'], action=ScroogeGen
).install('gen')

goal(name='protoc', action=ProtobufGen
).install('gen')

goal(name='antlr', dependencies=['bootstrap'], action=AntlrGen
).install('gen')

goal(name='checkstyle', action=Checkstyle, dependencies=['gen', 'resolve']
).install().with_description('Run checkstyle against java source code.')


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

goal(name='prepare', action=PrepareResources
).install('resources')


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

goal(name='markdown', action=MarkdownToHtml
).install('markdown').with_description('Generate html from markdown docs.')

goal(name='javadoc_publish', action=JavadocJarShim
).install('publish')

goal(name='scaladoc_publish', action=ScaladocJarShim
).install('publish')


# Bundling and publishing.

goal(name='jar', action=JarCreate, dependencies=['compile', 'resources', 'bootstrap']
).install('jar')

goal(name='binary', action=BinaryCreate, dependencies=['jar', 'bootstrap']
).install().with_description('Create a jvm binary jar.')

goal(name='bundle', action=BundleCreate, dependencies=['jar', 'bootstrap']
).install().with_description('Create an application bundle from binary targets.')

goal(name='check_published_deps', action=CheckPublishedDeps
).install('check_published_deps').with_description('Find references to outdated artifacts.')

goal(name='jar_create_publish', action=JarCreate, dependencies=['compile', 'resources']
).install('publish')

goal(name='publish', action=JarPublish
).install('publish').with_description('Publish artifacts.')


# Linting.

goal(name='check-exclusives', dependencies=['gen'], action=CheckExclusives
).install('check-exclusives').with_description('Check for exclusivity violations.')

goal(name='dup',action=DuplicateDetector,
).install('binary')

goal(name='detect-duplicates', action=DuplicateDetector, dependencies=['jar']
).install().with_description('Detect duplicate classes and resources on the classpath.')

goal(name='buildlint', action=BuildLint, dependencies=['compile']
).install()


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

goal(name='filedeps', action=FileDeps
).install('filedeps').with_description('Print out the source and BUILD files the target depends on.')

goal(name='pathdeps', action=PathDeps).install('pathdeps').with_description(
  'Print out all paths containing BUILD files the target depends on.')

goal(name='list', action=ListTargets
).install('list').with_description('List available BUILD targets.')


# IDE support.

goal(name='idea', action=IdeaGen, dependencies=['jar', 'bootstrap']
).install().with_description('Create an IntelliJ IDEA project from the given targets.')

goal(name='eclipse', action=EclipseGen, dependencies=['jar', 'bootstrap']
).install().with_description('Create an Eclipse project from the given targets.')


# Build graph information.

goal(name='provides', action=Provides, dependencies=['jar', 'bootstrap']
).install().with_description('Print the symbols provided by the given targets.')

goal(name='path', action=Path
).install().with_description('Find a dependency path from one target to another.')

goal(name='paths', action=Paths
).install().with_description('Find all dependency paths from one target to another.')

goal(name='dependees', action=ReverseDepmap
).install().with_description("Print the target's dependees.")

goal(name='depmap', action=Depmap
).install().with_description("Depict the target's dependencies.")

goal(name='dependencies', action=Dependencies
).install().with_description("Print the target's dependencies.")

goal(name='filemap', action=Filemap
).install().with_description('Outputs a mapping from source file to owning target.')

goal(name='minimize', action=MinimalCover
).install().with_description('Print the minimal cover of the given targets.')

goal(name='filter', action=Filter
).install().with_description('Filter the input targets based on various criteria.')

goal(name='sort', action=SortTargets
).install().with_description("Topologically sort the targets.")

goal(name='roots', action=ListRoots
).install('roots').with_description("Print the workspace's source roots and associated target types.")
