# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.doc import Page, Wiki, WikiArtifact
from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.build_lint import BuildLint
from pants.backend.core.tasks.builddictionary import BuildBuildDictionary
from pants.backend.core.tasks.check_exclusives import CheckExclusives
from pants.backend.core.tasks.clean import Invalidator, Cleaner, AsyncCleaner
from pants.backend.core.tasks.confluence_publish import ConfluencePublish
from pants.backend.core.tasks.dependees import ReverseDepmap
from pants.backend.core.tasks.filemap import Filemap
from pants.backend.core.tasks.filter import Filter
from pants.backend.core.tasks.list_goals import ListGoals
from pants.backend.core.tasks.listtargets import ListTargets
from pants.backend.core.tasks.markdown_to_html import MarkdownToHtml
from pants.backend.core.tasks.minimal_cover import MinimalCover
from pants.backend.core.tasks.pathdeps import PathDeps
from pants.backend.core.tasks.paths import Path, Paths
from pants.backend.core.tasks.prepare_resources import PrepareResources
from pants.backend.core.tasks.reporting_server import RunServer, KillServer
from pants.backend.core.tasks.roots import ListRoots
from pants.backend.core.tasks.sorttargets import SortTargets
from pants.backend.core.tasks.targets_help import TargetsHelp
from pants.backend.core.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.base.build_environment import get_buildroot, get_scm, pants_version, set_scm
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.config import Config
from pants.base.source_root import SourceRoot
from pants.commands.goal_runner import GoalRunner
from pants.goal.task_registrar import TaskRegistrar as task
from pants.goal.phase import Phase


class BuildFilePath(object):
  """Returns path containing this ``BUILD`` file."""
  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self):
    return os.path.join(get_buildroot(), self.rel_path)


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'dependencies': Dependencies,
      'page': Page,
      'resources': Resources,
      'wiki': Wiki,
    },
    objects={
      'config': Config,
      'ConfluencePublish': ConfluencePublish,
      'get_buildroot': get_buildroot,
      'get_scm': get_scm,
      'pants_version': pants_version,
      'goal': task,
      'pants': lambda x: x,
      'phase': Phase,
      'set_scm': set_scm,
      'wiki_artifact': WikiArtifact,
    },
    context_aware_object_factories={
      'source_root': SourceRoot,
      'globs': Globs,
      'rglobs': RGlobs,
      'zglobs': ZGlobs,
      'buildfile_path': BuildFilePath,
    }
  )


def register_commands():
  GoalRunner._register()


def register_goals():
  # Getting help.
  task(name='goals', action=ListGoals
  ).install().with_description('List all documented goals.')

  task(name='targets', action=TargetsHelp
  ).install().with_description('List all target types.')

  task(name='builddict', action=BuildBuildDictionary
  ).install()


  # Cleaning.
  invalidate = task(name='invalidate', action=Invalidator, dependencies=['ng-killall'])
  invalidate.install().with_description('Invalidate all targets.')

  clean_all = task(name='clean-all', action=Cleaner, dependencies=['invalidate']).install()
  clean_all.with_description('Clean all build output.')
  clean_all.install(invalidate, first=True)

  clean_all_async = task(name='clean-all-async', action=AsyncCleaner, dependencies=['invalidate']
  ).install().with_description('Clean all build output in a background process.')
  clean_all_async.install(invalidate, first=True)

  # Reporting.

  task(name='server', action=RunServer, serialize=False
  ).install().with_description('Run the pants reporting server.')

  task(name='killserver', action=KillServer, serialize=False
  ).install().with_description('Kill the reporting server.')


  # Bootstrapping.
  task(name='prepare', action=PrepareResources
  ).install('resources')

  task(name='markdown', action=MarkdownToHtml
  ).install('markdown').with_description('Generate html from markdown docs.')


  # Linting.

  task(name='check-exclusives', dependencies=['gen'], action=CheckExclusives
  ).install('check-exclusives').with_description('Check for exclusivity violations.')

  task(name='buildlint', action=BuildLint, dependencies=['compile']
  ).install()

  task(name='pathdeps', action=PathDeps).install('pathdeps').with_description(
    'Print out all paths containing BUILD files the target depends on.')

  task(name='list', action=ListTargets
  ).install('list').with_description('List available BUILD targets.')


  # Build graph information.

  task(name='path', action=Path
  ).install().with_description('Find a dependency path from one target to another.')

  task(name='paths', action=Paths
  ).install().with_description('Find all dependency paths from one target to another.')

  task(name='dependees', action=ReverseDepmap
  ).install().with_description("Print the target's dependees.")

  task(name='filemap', action=Filemap
  ).install().with_description('Outputs a mapping from source file to owning target.')

  task(name='minimize', action=MinimalCover
  ).install().with_description('Print the minimal cover of the given targets.')

  task(name='filter', action=Filter
  ).install().with_description('Filter the input targets based on various criteria.')

  task(name='sort', action=SortTargets
  ).install().with_description("Topologically sort the targets.")

  task(name='roots', action=ListRoots
  ).install('roots').with_description("Print the workspace's source roots and associated target types.")
