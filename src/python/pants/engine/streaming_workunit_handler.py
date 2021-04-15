# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence, Tuple

from pants.base.specs import Specs
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestContents, Snapshot
from pants.engine.internals import native_engine
from pants.engine.internals.scheduler import SchedulerSession, Workunit
from pants.engine.internals.selectors import Params
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.goal.run_tracker import RunTracker
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# Streaming workunits plugin API
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetInfo:
    filename: str


@dataclass(frozen=True)
class ExpandedSpecs:
    targets: dict[str, list[TargetInfo]]


@dataclass(frozen=True)
class StreamingWorkunitContext:
    _scheduler: SchedulerSession
    _run_tracker: RunTracker
    _specs: Specs
    _options_bootstrapper: OptionsBootstrapper

    @property
    def run_tracker(self) -> RunTracker:
        """Returns the RunTracker for the current run of Pants."""
        return self._run_tracker

    def single_file_digests_to_bytes(self, digests: Sequence[Digest]) -> tuple[bytes, ...]:
        """Given a list of Digest objects, each representing the contents of a single file, return a
        list of the bytes corresponding to each of those Digests in sequence."""
        return self._scheduler.single_file_digests_to_bytes(digests)

    def snapshots_to_file_contents(
        self, snapshots: Sequence[Snapshot]
    ) -> Tuple[DigestContents, ...]:
        """Given a sequence of Snapshot objects, return a tuple of DigestContents representing the
        files contained in those `Snapshot`s in sequence."""
        return self._scheduler.snapshots_to_file_contents(snapshots)

    def ensure_remote_has_recursive(self, digests: Sequence[Digest]) -> None:
        """Invoke the internal ensure_remote_has_recursive function, which ensures that a remote
        ByteStore, if it exists, has a copy of the files fingerprinted by each Digest."""
        return self._scheduler.ensure_remote_has_recursive(digests)

    def get_observation_histograms(self):
        """Invoke the internal get_observation_histograms function, which serializes histograms
        generated from Pants-internal observation metrics observed during the current run of Pants.

        These metrics are useful for debugging Pants internals.
        """
        return self._scheduler.get_observation_histograms()

    def get_expanded_specs(self) -> ExpandedSpecs:
        """Return a dict containing the canonicalized addresses of the specs for this run, and what
        files they expand to."""

        (unexpanded_addresses,) = self._scheduler.product_request(
            Addresses, [Params(self._specs, self._options_bootstrapper)]
        )

        expanded_targets = self._scheduler.product_request(
            Targets, [Params(Addresses([addr])) for addr in unexpanded_addresses]
        )
        targets_dict: dict[str, list[TargetInfo]] = {}
        for addr, targets in zip(unexpanded_addresses, expanded_targets):
            targets_dict[addr.spec] = [
                TargetInfo(
                    filename=(
                        tgt.address.filename if tgt.address.is_file_target else str(tgt.address)
                    )
                )
                for tgt in targets
            ]
        return ExpandedSpecs(targets=targets_dict)


class WorkunitsCallback(ABC):
    @abstractmethod
    def __call__(
        self,
        *,
        started_workunits: tuple[Workunit, ...],
        completed_workunits: tuple[Workunit, ...],
        finished: bool,
        context: StreamingWorkunitContext,
    ) -> None:
        """
        :started_workunits: Workunits that have started but not completed.
        :completed_workunits: Workunits that have completed.
        :finished: True when the last chunk of workunit data is reported to the callback.
        :context: A context providing access to functionality relevant to the run.
        """

    @property
    @abstractmethod
    def can_finish_async(self) -> bool:
        """Can this callback finish its work in the background after the Pants run has already
        completed?

        The main reason to `return False` is if your callback logs in its final call, when
        `finished=True`, as it may end up logging to `.pantsd.d/pants.log` instead of the console,
        which is harder for users to find. Otherwise, most callbacks should return `True` to avoid
        slowing down Pants from finishing the run.
        """


@dataclass(frozen=True)
class WorkunitsCallbackFactory:
    """A wrapper around a callable that constructs WorkunitsCallbacks.

    NB: This extra wrapping is because subtyping is not supported in the return position of a
    rule. See #11354 for discussion of that limitation.
    """

    callback_factory: Callable[[], WorkunitsCallback]


class WorkunitsCallbackFactories(Tuple[WorkunitsCallbackFactory, ...]):
    """A list of registered factories for WorkunitsCallback instances."""


@union
class WorkunitsCallbackFactoryRequest:
    """A request for a particular WorkunitsCallbackFactory."""


@rule
async def construct_workunits_callback_factories(
    union_membership: UnionMembership,
) -> WorkunitsCallbackFactories:
    request_types = union_membership.get(WorkunitsCallbackFactoryRequest)
    workunit_callback_factories = await MultiGet(
        Get(WorkunitsCallbackFactory, WorkunitsCallbackFactoryRequest, request_type())
        for request_type in request_types
    )
    return WorkunitsCallbackFactories(workunit_callback_factories)


# -----------------------------------------------------------------------------------------------
# Streaming workunits handler
# -----------------------------------------------------------------------------------------------


class StreamingWorkunitHandler:
    """Periodically calls each registered WorkunitsCallback in a dedicated thread.

    This class should be used as a context manager.
    """

    def __init__(
        self,
        scheduler: SchedulerSession,
        run_tracker: RunTracker,
        callbacks: Iterable[WorkunitsCallback],
        options_bootstrapper: OptionsBootstrapper,
        specs: Specs,
        report_interval_seconds: float,
        pantsd: bool,
        max_workunit_verbosity: LogLevel = LogLevel.TRACE,
    ) -> None:
        scheduler = scheduler.isolated_shallow_clone("streaming_workunit_handler_session")
        self.callbacks = callbacks
        self.context = StreamingWorkunitContext(
            _scheduler=scheduler,
            _run_tracker=run_tracker,
            _specs=specs,
            _options_bootstrapper=options_bootstrapper,
        )
        self.thread_runner = (
            _InnerHandler(
                scheduler=scheduler,
                context=self.context,
                callbacks=self.callbacks,
                report_interval=report_interval_seconds,
                # TODO(10092) The max verbosity should be a per-client setting, rather than a global
                #  setting.
                max_workunit_verbosity=max_workunit_verbosity,
                pantsd=pantsd,
            )
            if callbacks
            else None
        )

    def __enter__(self) -> None:
        if not self.thread_runner:
            return
        self.thread_runner.start()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self.thread_runner:
            return
        self.thread_runner.end()
        if exc_type is not None:
            self.thread_runner.join()


class _InnerHandler(threading.Thread):
    def __init__(
        self,
        scheduler: Any,
        context: StreamingWorkunitContext,
        callbacks: Iterable[WorkunitsCallback],
        report_interval: float,
        max_workunit_verbosity: LogLevel,
        pantsd: bool,
    ) -> None:
        super().__init__(daemon=True)
        self.scheduler = scheduler
        self.context = context
        self.stop_request = threading.Event()
        self.report_interval = report_interval
        self.callbacks = callbacks
        self.max_workunit_verbosity = max_workunit_verbosity
        # TODO: Have a thread per callback so that some callbacks can always finish async even
        #  if others must be finished synchronously.
        self.block_until_complete = not pantsd or any(
            callback.can_finish_async is False for callback in self.callbacks
        )
        # Get the parent thread's logging destination. Note that this thread has not yet started
        # as we are only in the constructor.
        self.logging_destination = native_engine.stdio_thread_get_destination()

    def poll_workunits(self, *, finished: bool) -> None:
        workunits = self.scheduler.poll_workunits(self.max_workunit_verbosity)
        for callback in self.callbacks:
            callback(
                started_workunits=workunits["started"],
                completed_workunits=workunits["completed"],
                finished=finished,
                context=self.context,
            )

    def run(self) -> None:
        # First, set the thread's logging destination to the parent thread's, meaning the console.
        native_engine.stdio_thread_set_destination(self.logging_destination)
        while not self.stop_request.isSet():  # type: ignore[attr-defined]
            self.poll_workunits(finished=False)
            self.stop_request.wait(timeout=self.report_interval)
        else:
            # Make one final call. Note that this may run after the Pants run has already
            # completed, depending on whether the thread was joined or not.
            self.poll_workunits(finished=True)

    def end(self) -> None:
        self.stop_request.set()
        if self.block_until_complete:
            super().join()


def rules():
    return [
        QueryRule(WorkunitsCallbackFactories, (UnionMembership,)),
        QueryRule(Targets, (Addresses,)),
        QueryRule(Addresses, (Specs, OptionsBootstrapper)),
        *collect_rules(),
    ]
