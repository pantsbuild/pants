# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.fs import PathGlobs, Snapshot, create_fs_rules
from pants.engine.legacy.graph import eager_fileset_with_spec
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class SourcesTestBase(SchedulerTestBase):
  def sources_for(self, file_paths):
    scheduler = self.mk_scheduler(
      create_fs_rules(),
      project_tree=FileSystemProjectTree(self.build_root),
    )

    file_paths_tuple = tuple(file_paths)
    path_globs = PathGlobs.create(file_paths_tuple)
    snapshot = self.execute_expecting_one_result(scheduler, Snapshot, path_globs).value

    return eager_fileset_with_spec('', {'globs': file_paths_tuple}, snapshot)
