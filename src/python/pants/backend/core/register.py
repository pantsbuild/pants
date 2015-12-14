# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.builddictionary import BuildBuildDictionary
from pants.backend.core.tasks.cloc import CountLinesOfCode
from pants.backend.core.tasks.dependees import ReverseDepmap
from pants.backend.core.tasks.filemap import Filemap
from pants.backend.core.tasks.filter import Filter
from pants.backend.core.tasks.list_owners import ListOwners
from pants.backend.core.tasks.listtargets import ListTargets
from pants.backend.core.tasks.minimal_cover import MinimalCover
from pants.backend.core.tasks.pathdeps import PathDeps
from pants.backend.core.tasks.paths import Path, Paths
from pants.backend.core.tasks.sorttargets import SortTargets
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='builddict', action=BuildBuildDictionary).install()

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
