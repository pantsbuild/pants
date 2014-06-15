# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.dirutil.fileset import Fileset
from twitter.common.quantity import Amount, Time

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.doc import Page, Wiki
from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.build_lint import BuildLint
from pants.backend.core.tasks.builddictionary import BuildBuildDictionary
from pants.backend.core.tasks.check_exclusives import CheckExclusives
from pants.backend.core.tasks.clean import Invalidator, Cleaner, AsyncCleaner
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
from pants.base.build_environment import get_buildroot, get_version, get_scm, set_scm
from pants.base.config import Config
from pants.base.source_root import SourceRoot
from pants.goal import Goal as goal, Group as group
from pants.goal import Goal, Group, Phase


class BuildFilePath(object):
  def __init__(self, rel_path):
    self.rel_path = rel_path

  def __call__(self, *args, **kwargs):
    return os.path.join(get_buildroot(), self.rel_path)


def applicative_path_relative_util_aliases():
  return {
    'source_root': SourceRoot,
    'globs': Globs,
    'rglobs': RGlobs,
    'zglobs': ZGlobs,
    'buildfile_path': BuildFilePath,
  }


def partial_path_relative_util_aliases():
  return {}


def target_creation_utils():
  return {}


# aliases
def target_aliases():
  return {
    'dependencies': Dependencies,
    'page': Page,
    'resources': Resources,
    'wiki': Wiki,
  }


def object_aliases():
  return {
    'Amount': Amount,
    'config': Config,
    'get_buildroot': get_buildroot,
    'get_scm': get_scm,
    'get_version': get_version,
    'goal': Goal,
    'group': Group,
    'pants': lambda x: x,
    'phase': Phase,
    'set_scm': set_scm,
    'Time': Time,
  }


def register_commands():
  pass


def register_goals():
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


  # Reporting.

  goal(name='server', action=RunServer, serialize=False
  ).install().with_description('Run the pants reporting server.')

  goal(name='killserver', action=KillServer, serialize=False
  ).install().with_description('Kill the reporting server.')


  # Bootstrapping.
  goal(name='prepare', action=PrepareResources
  ).install('resources')

  goal(name='markdown', action=MarkdownToHtml
  ).install('markdown').with_description('Generate html from markdown docs.')


  # Linting.

  goal(name='check-exclusives', dependencies=['gen'], action=CheckExclusives
  ).install('check-exclusives').with_description('Check for exclusivity violations.')

  goal(name='buildlint', action=BuildLint, dependencies=['compile']
  ).install()

  goal(name='pathdeps', action=PathDeps).install('pathdeps').with_description(
    'Print out all paths containing BUILD files the target depends on.')

  goal(name='list', action=ListTargets
  ).install('list').with_description('List available BUILD targets.')


  # Build graph information.

  goal(name='path', action=Path
  ).install().with_description('Find a dependency path from one target to another.')

  goal(name='paths', action=Paths
  ).install().with_description('Find all dependency paths from one target to another.')

  goal(name='dependees', action=ReverseDepmap
  ).install().with_description("Print the target's dependees.")

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
