# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.exp.fs import create_fs_tasks
from pants.engine.exp.parsers import SymbolTable
from pants.engine.exp.scheduler import LocalScheduler
from pants.engine.exp.storage import Storage
from pants.util.dirutil import safe_mkdtemp, safe_rmtree


class EmptyTable(SymbolTable):
  @classmethod
  def table(cls):
    return {}


class SchedulerTestBase(object):
  def mk_scheduler(self, tasks=None, goals=None, storage=None, symbol_table_cls=EmptyTable):
    """Creates a Scheduler with "native" tasks already included, and the given additional tasks."""
    goals = goals or dict()
    tasks = tasks or []
    storage = storage or Storage.create(in_memory=True)

    work_dir = safe_mkdtemp()
    self.addCleanup(safe_rmtree, work_dir)
    build_root = os.path.join(work_dir, 'build_root')

    project_tree_key = storage.put(FileSystemProjectTree(build_root))
    tasks = list(tasks) + create_fs_tasks(project_tree_key)
    scheduler = LocalScheduler(goals,
                               tasks,
                               storage,
                               symbol_table_cls)
    return scheduler, build_root
