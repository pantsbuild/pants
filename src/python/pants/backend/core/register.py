# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from pants.backend.core.from_target import FromTarget
from pants.backend.core.targets.dependencies import Dependencies, DeprecatedDependencies
from pants.backend.core.targets.doc import Page, Wiki, WikiArtifact
from pants.backend.core.targets.prep_command import PrepCommand
from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.bash_completion import BashCompletionTask
from pants.backend.core.tasks.builddictionary import BuildBuildDictionary
from pants.backend.core.tasks.changed_target_goals import CompileChanged, TestChanged
from pants.backend.core.tasks.clean import Cleaner, Invalidator
from pants.backend.core.tasks.confluence_publish import ConfluencePublish
from pants.backend.core.tasks.deferred_sources_mapper import DeferredSourcesMapper
from pants.backend.core.tasks.dependees import ReverseDepmap
from pants.backend.core.tasks.explain_options_task import ExplainOptionsTask
from pants.backend.core.tasks.filemap import Filemap
from pants.backend.core.tasks.filter import Filter
from pants.backend.core.tasks.list_goals import ListGoals
from pants.backend.core.tasks.list_owners import ListOwners
from pants.backend.core.tasks.listtargets import ListTargets
from pants.backend.core.tasks.markdown_to_html import MarkdownToHtml
from pants.backend.core.tasks.minimal_cover import MinimalCover
from pants.backend.core.tasks.noop import NoopCompile, NoopTest
from pants.backend.core.tasks.pathdeps import PathDeps
from pants.backend.core.tasks.paths import Path, Paths
from pants.backend.core.tasks.reporting_server import KillServer, RunServer
from pants.backend.core.tasks.roots import ListRoots
from pants.backend.core.tasks.run_prep_command import RunPrepCommand
from pants.backend.core.tasks.sorttargets import SortTargets
from pants.backend.core.tasks.targets_help import TargetsHelp
from pants.backend.core.tasks.what_changed import WhatChanged
from pants.backend.core.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.base.build_environment import get_buildroot, pants_version
from pants.base.source_root import SourceRoot
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


class BuildFilePath(object):
  """Returns path containing this ``BUILD`` file."""

  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self):
    return os.path.join(get_buildroot(), self.rel_path)


def build_file_aliases():
  return BuildFileAliases(
    targets={
      # NB: the 'dependencies' alias is deprecated in favor of the 'target' alias
      'dependencies': DeprecatedDependencies,
      'page': Page,
      'prep_command': PrepCommand,
      'resources': Resources,
      'target': Dependencies,
    },
    objects={
      'ConfluencePublish': ConfluencePublish,
      'get_buildroot': get_buildroot,
      'pants_version': pants_version,
      'wiki_artifact': WikiArtifact,
      'Wiki': Wiki,
    },
    context_aware_object_factories={
      'buildfile_path': BuildFilePath,
      'globs': Globs.factory,
      'from_target': FromTarget,
      'rglobs': RGlobs.factory,
      'source_root': SourceRoot.factory,
      'zglobs': ZGlobs.factory,
    }
  )


def register_goals():
  # TODO: Most of these (and most tasks in other backends) can probably have their
  # with_description() removed, as their docstring will be used instead.

  # Getting help.
  task(name='goals', action=ListGoals).install().with_description('List all documented goals.')

  task(name='targets', action=TargetsHelp).install().with_description(
      'List target types and BUILD file symbols (python_tests, jar, etc).')

  task(name='builddict', action=BuildBuildDictionary).install()

  # Cleaning.
  invalidate = task(name='invalidate', action=Invalidator)
  invalidate.install().with_description('Invalidate all targets.')

  clean_all = task(name='clean-all', action=Cleaner).install()
  clean_all.with_description('Clean all build output.')
  clean_all.install(invalidate, first=True)

  class AsyncCleaner(Cleaner):
    def execute(self):
      print('The `clean-all-async` goal is deprecated and currently just forwards to `clean-all`.',
            file=sys.stderr)
      print('Please update your usages to `clean-all`.', file=sys.stderr)
      super(AsyncCleaner, self).execute()
  clean_all_async = task(name='clean-all-async', action=AsyncCleaner).install().with_description(
      '[deprecated] Clean all build output in a background process.')
  clean_all_async.install(invalidate, first=True)

  # Reporting.
  task(name='server', action=RunServer, serialize=False).install().with_description(
      'Run the pants reporting server.')

  task(name='killserver', action=KillServer, serialize=False).install().with_description(
      'Kill the reporting server.')

  task(name='markdown', action=MarkdownToHtml).install('markdown').with_description(
      'Generate html from markdown docs.')

  # Linting.
  task(name='pathdeps', action=PathDeps).install('pathdeps').with_description(
      'Print out all paths containing BUILD files the target depends on.')

  task(name='list', action=ListTargets).install('list').with_description(
      'List available BUILD targets.')

  # Build graph information.
  task(name='path', action=Path).install().with_description(
      'Find a dependency path from one target to another.')

  task(name='paths', action=Paths).install().with_description(
      'Find all dependency paths from one target to another.')

  task(name='dependees', action=ReverseDepmap).install().with_description(
      "Print the target's dependees.")

  task(name='filemap', action=Filemap).install().with_description(
      'Outputs a mapping from source file to owning target.')

  task(name='minimize', action=MinimalCover).install().with_description(
      'Print the minimal cover of the given targets.')

  task(name='filter', action=Filter).install()

  task(name='sort', action=SortTargets).install().with_description(
      'Topologically sort the targets.')

  task(name='roots', action=ListRoots).install('roots').with_description(
      "Print the workspace's source roots and associated target types.")

  task(name='run_prep_command', action=RunPrepCommand).install('test', first=True).with_description(
      "Run a command before tests")

  task(name='changed', action=WhatChanged).install().with_description(
      'Print the targets changed since some prior commit.')

  task(name='list-owners', action=ListOwners).install().with_description(
      'Print targets that own the specified source')

  # Stub for other goals to schedule 'compile'. See noop.py for more on why this is useful.
  task(name='compile', action=NoopCompile).install('compile')
  task(name='compile-changed', action=CompileChanged).install().with_description(
    'Compile changed targets.')

  # Stub for other goals to schedule 'test'. See noop.py for more on why this is useful.
  task(name='test', action=NoopTest).install('test')
  task(name='test-changed', action=TestChanged).install().with_description(
    'Test changed targets.')

  task(name='deferred-sources', action=DeferredSourcesMapper).install().with_description(
    'Map unpacked sources from archives.')

  task(name='bash-completion', action=BashCompletionTask).install().with_description(
    'Dump bash shell script for autocompletion of pants command lines.')

  task(name='options', action=ExplainOptionsTask).install().with_description(
    'List what options pants has set.')
