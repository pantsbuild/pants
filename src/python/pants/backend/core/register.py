# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.from_target import FromTarget
from pants.backend.core.targets.doc import Page, Wiki, WikiArtifact
from pants.backend.core.tasks.builddictionary import BuildBuildDictionary
from pants.backend.core.tasks.cloc import CountLinesOfCode
from pants.backend.core.tasks.confluence_publish import ConfluencePublish
from pants.backend.core.tasks.dependees import ReverseDepmap
from pants.backend.core.tasks.filemap import Filemap
from pants.backend.core.tasks.filter import Filter
from pants.backend.core.tasks.list_owners import ListOwners
from pants.backend.core.tasks.listtargets import ListTargets
from pants.backend.core.tasks.markdown_to_html import MarkdownToHtml
from pants.backend.core.tasks.minimal_cover import MinimalCover
from pants.backend.core.tasks.pathdeps import PathDeps
from pants.backend.core.tasks.paths import Path, Paths
from pants.backend.core.tasks.sorttargets import SortTargets
from pants.backend.core.wrapped_globs import Globs, RGlobs, ZGlobs
from pants.base.build_environment import get_buildroot, pants_version
from pants.base.source_root import SourceRoot
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.prep_command import PrepCommand
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
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
      'page': Page,
      'prep_command': PrepCommand,
      'resources': Resources,
      'target': Target,
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
  task(name='builddict', action=BuildBuildDictionary).install()
  task(name='markdown', action=MarkdownToHtml).install()

  task(name='pathdeps', action=PathDeps).install()
  task(name='list', action=ListTargets).install()

  # Build graph information.
  task(name='path', action=Path).install()
  task(name='paths', action=Paths).install()
  task(name='dependees', action=ReverseDepmap).install()
  task(name='filemap', action=Filemap).install()
  task(name='minimize', action=MinimalCover).install()
  task(name='filter', action=Filter).install()
  task(name='sort', action=SortTargets).install()
  task(name='cloc', action=CountLinesOfCode).install()
  task(name='list-owners', action=ListOwners).install()
