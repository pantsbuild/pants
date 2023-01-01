# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path

from pants.engine.internals.native_engine import PyExecutor
from pants.engine.internals.scheduler import Scheduler, SchedulerSession
from pants.engine.unions import UnionMembership
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS, DEFAULT_LOCAL_STORE_OPTIONS
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import safe_mkdtemp
from pants.util.logging import LogLevel


class SchedulerTestBase:
    """A mixin for classes which need to create temporary schedulers.

    TODO: In the medium term, this should be removed in favor of RuleRunner.
    """

    _executor = PyExecutor(core_threads=2, max_threads=4)

    def mk_scheduler(
        self,
        tmp_path: Path,
        rules,
        include_trace_on_error: bool = True,
        max_workunit_verbosity: LogLevel = LogLevel.DEBUG,
    ) -> SchedulerSession:
        """Creates a SchedulerSession for a Scheduler with the given Rules installed."""

        build_root = tmp_path / "build_root"
        build_root.mkdir(parents=True, exist_ok=True)

        local_execution_root_dir = os.path.realpath(safe_mkdtemp())
        named_caches_dir = os.path.realpath(safe_mkdtemp())
        scheduler = Scheduler(
            ignore_patterns=[],
            use_gitignore=False,
            build_root=build_root.as_posix(),
            local_execution_root_dir=local_execution_root_dir,
            named_caches_dir=named_caches_dir,
            ca_certs_path=None,
            rules=rules,
            union_membership=UnionMembership({}),
            executor=self._executor,
            execution_options=DEFAULT_EXECUTION_OPTIONS,
            local_store_options=DEFAULT_LOCAL_STORE_OPTIONS,
            include_trace_on_error=include_trace_on_error,
        )
        return scheduler.new_session(
            build_id="buildid_for_test",
            max_workunit_level=max_workunit_verbosity,
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
        return [state.value for _, state in returns]

    def execute_expecting_one_result(self, scheduler, product, subject):
        request = scheduler.execution_request([product], [subject])
        returns, throws = scheduler.execute(request)

        if throws:
            _, state = throws[0]
            raise state.exc

        assert len(returns) == 1

        _, state = returns[0]
        return state
