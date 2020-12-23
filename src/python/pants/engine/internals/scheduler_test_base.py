# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
from dataclasses import asdict

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.internals.native import Native
from pants.engine.internals.native_engine import PyExecutor
from pants.engine.internals.scheduler import Scheduler
from pants.engine.unions import UnionMembership
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS, ExecutionOptions
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import safe_mkdtemp, safe_rmtree


class SchedulerTestBase:
    """A mixin for classes (tests, presumably) which need to create temporary schedulers.

    TODO: In the medium term, this should be part of pants_test.test_base.TestBase.
    """

    _native = Native()
    _executor = PyExecutor(2, 4)

    def _create_work_dir(self):
        work_dir = safe_mkdtemp()
        self.addCleanup(safe_rmtree, work_dir)
        return work_dir

    def mk_fs_tree(self, build_root_src=None, ignore_patterns=None, work_dir=None):
        """Create a temporary FilesystemProjectTree.

        :param build_root_src: Optional directory to pre-populate from; otherwise, empty.
        :returns: A FilesystemProjectTree.
        """
        work_dir = work_dir or self._create_work_dir()
        build_root = os.path.join(work_dir, "build_root")
        if build_root_src is not None:
            shutil.copytree(build_root_src, build_root, symlinks=True)
        else:
            os.makedirs(build_root)
        return FileSystemProjectTree(build_root, ignore_patterns=ignore_patterns)

    def mk_scheduler(
        self,
        rules=None,
        project_tree=None,
        work_dir=None,
        include_trace_on_error=True,
        should_report_workunits=False,
        execution_options=None,
        ca_certs_path=None,
    ):
        """Creates a SchedulerSession for a Scheduler with the given Rules installed."""
        rules = rules or []
        work_dir = work_dir or self._create_work_dir()
        project_tree = project_tree or self.mk_fs_tree(work_dir=work_dir)
        local_store_dir = os.path.realpath(safe_mkdtemp())
        local_execution_root_dir = os.path.realpath(safe_mkdtemp())
        named_caches_dir = os.path.realpath(safe_mkdtemp())
        if execution_options is not None:
            eo = asdict(DEFAULT_EXECUTION_OPTIONS)
            eo.update(execution_options)
            execution_options = ExecutionOptions(**eo)
        scheduler = Scheduler(
            native=self._native,
            ignore_patterns=project_tree.ignore_patterns,
            use_gitignore=False,
            build_root=project_tree.build_root,
            local_store_dir=local_store_dir,
            local_execution_root_dir=local_execution_root_dir,
            named_caches_dir=named_caches_dir,
            ca_certs_path=ca_certs_path,
            rules=rules,
            union_membership=UnionMembership({}),
            executor=self._executor,
            execution_options=execution_options or DEFAULT_EXECUTION_OPTIONS,
            include_trace_on_error=include_trace_on_error,
        )
        return scheduler.new_session(
            build_id="buildid_for_test",
            should_report_workunits=should_report_workunits,
        )

    def execute(self, scheduler, product, *subjects):
        """Runs an ExecutionRequest for the given product and subjects, and returns the result
        value."""
        request = scheduler.execution_request([product], subjects)
        returns, throws = scheduler.execute(request)
        if throws:
            with temporary_file_path(cleanup=False, suffix=".dot") as dot_file:
                scheduler.visualize_graph_to_file(dot_file)
                raise ValueError(f"At least one root failed: {throws}. Visualized as {dot_file}")
        return list(state.value for _, state in returns)

    def execute_expecting_one_result(self, scheduler, product, subject):
        request = scheduler.execution_request([product], [subject])
        returns, throws = scheduler.execute(request)

        if throws:
            _, state = throws[0]
            raise state.exc

        self.assertEqual(len(returns), 1)

        _, state = returns[0]
        return state
