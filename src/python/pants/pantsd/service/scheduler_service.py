# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import List, Optional, Tuple, cast

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import Specs
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.internals.scheduler import ExecutionError, ExecutionTimeoutError
from pants.engine.unions import UnionMembership
from pants.goal.run_tracker import RunTracker
from pants.init.engine_initializer import LegacyGraphScheduler, LegacyGraphSession
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
    """The pantsd scheduler service.

    This service holds an online Scheduler instance that is primed via watchman filesystem events.
    """

    # The interval on which we will long-poll the invalidation globs. If a glob changes, the poll
    # will return immediately, so this value primarily affects how frequently the `run` method
    # will check the terminated condition.
    INVALIDATION_POLL_INTERVAL = 0.5

    def __init__(
        self,
        *,
        fs_event_service: Optional[FSEventService],
        legacy_graph_scheduler: LegacyGraphScheduler,
        build_root: str,
        invalidation_globs: List[str],
        union_membership: UnionMembership,
    ) -> None:
        """
        :param fs_event_service: An unstarted FSEventService instance for setting up filesystem event handlers.
        :param legacy_graph_scheduler: The LegacyGraphScheduler instance for graph construction.
        :param build_root: The current build root.
        :param invalidation_globs: A list of `globs` that when encountered in filesystem event
                                   subscriptions will tear down the daemon.
        """
        super().__init__()
        self._fs_event_service = fs_event_service
        self._graph_helper = legacy_graph_scheduler
        self._build_root = build_root
        self._union_membership = union_membership

        self._scheduler = legacy_graph_scheduler.scheduler
        # This session is only used for checking whether any invalidation globs have been invalidated.
        # It is not involved with a build itself; just with deciding when we should restart pantsd.
        self._scheduler_session = self._scheduler.new_session(
            zipkin_trace_v2=False, build_id="scheduler_service_session",
        )
        self._logger = logging.getLogger(__name__)

        # NB: We declare these as a single field so that they can be changed atomically
        # by add_invalidation_glob.
        self._invalidation_globs_and_snapshot: Tuple[Tuple[str, ...], Optional[Snapshot]] = (
            tuple(invalidation_globs),
            None,
        )

    def _get_snapshot(self, globs: Tuple[str, ...], poll: bool) -> Optional[Snapshot]:
        """Returns a Snapshot of the input globs.

        If poll=True, will wait for up to INVALIDATION_POLL_INTERVAL for the globs to have changed,
        and will return None if they have not changed.
        """
        timeout = self.INVALIDATION_POLL_INTERVAL if poll else None
        try:
            snapshot = self._scheduler_session.product_request(
                Snapshot, subjects=[PathGlobs(globs)], poll=poll, timeout=timeout,
            )[0]
            return cast(Snapshot, snapshot)
        except ExecutionTimeoutError:
            if poll:
                return None
            raise

    def setup(self, services):
        """Service setup."""
        super().setup(services)

        # N.B. We compute the invalidating fileset eagerly at launch with an assumption that files
        # that exist at startup are the only ones that can affect the running daemon.
        globs, _ = self._invalidation_globs_and_snapshot
        self._invalidation_globs_and_snapshot = (globs, self._get_snapshot(globs, poll=False))
        self._logger.info("watching invalidation patterns: {}".format(globs))

    def add_invalidation_glob(self, glob: str):
        """Add an invalidation glob to monitoring after startup.

        NB: This exists effectively entirely because pantsd needs to be fully started before writing
        its pid file: all other globs should be passed via the constructor.
        """
        self._logger.info("adding invalidation pattern: {}".format(glob))

        # Check one more time synchronously with our current set of globs.
        self._check_invalidation_globs(poll=False)

        # Synchronously invalidate the path on disk to prevent races with async invalidation, which
        # might otherwise take time to notice that the file had been created.
        self._scheduler.invalidate_files([glob])

        # Swap out the globs and snapshot.
        globs, _ = self._invalidation_globs_and_snapshot
        globs = globs + (glob,)
        self._invalidation_globs_and_snapshot = (globs, self._get_snapshot(globs, poll=False))

    def _check_invalidation_globs(self, poll: bool):
        """Check the digest of our invalidation Snapshot and exit if it has changed."""
        globs, invalidation_snapshot = self._invalidation_globs_and_snapshot
        assert invalidation_snapshot is not None, "Service.setup was not called."

        snapshot = self._get_snapshot(globs, poll=poll)
        if snapshot is None or snapshot.digest == invalidation_snapshot.digest:
            return

        before = set(invalidation_snapshot.files + invalidation_snapshot.dirs)
        after = set(snapshot.files + snapshot.dirs)
        added = after - before
        removed = before - after
        if added or removed:
            description = f"+{added or '{}'}, -{removed or '{}'}"
        else:
            description = f"content changed ({snapshot.digest} fs {invalidation_snapshot.digest})"
        self._logger.critical(
            f"saw filesystem changes covered by invalidation globs: {description}. terminating the daemon."
        )
        self.terminate()

    def _check_invalidation_watcher_liveness(self):
        try:
            self._scheduler.check_invalidation_watcher_liveness()
        except Exception as e:
            # Watcher failed for some reason
            self._logger.critical(f"The scheduler was invalidated: {e}")
            self.terminate()

    def prepare_graph(self, options: Options) -> LegacyGraphSession:
        # If any nodes exist in the product graph, wait for the initial watchman event to avoid
        # racing watchman startup vs invalidation events.
        if self._fs_event_service is not None and self._scheduler.graph_len() > 0:
            self._logger.debug(
                f"fs event service is running and graph_len > 0: waiting for initial watchman event"
            )
            self._fs_event_service.await_started()

        global_options = options.for_global_scope()
        build_id = RunTracker.global_instance().run_id
        v2_ui = global_options.get("v2_ui", False)
        use_colors = global_options.get("colors", True)
        zipkin_trace_v2 = options.for_scope("reporting").zipkin_trace_v2
        return self._graph_helper.new_session(
            zipkin_trace_v2, build_id, v2_ui=v2_ui, use_colors=use_colors
        )

    def graph_run_v2(
        self,
        session: LegacyGraphSession,
        specs: Specs,
        options: Options,
        options_bootstrapper: OptionsBootstrapper,
    ) -> int:
        """Perform an entire v2 run.

        The exit_code in the return indicates whether any issue was encountered.
        """

        global_options = options.for_global_scope()
        perform_loop = global_options.get("loop", False)
        v2 = global_options.v2

        if not perform_loop:
            return self._body(session, options, options_bootstrapper, specs, v2, poll=False)

        iterations = global_options.loop_max
        exit_code = PANTS_SUCCEEDED_EXIT_CODE

        while iterations and not self._state.is_terminating:
            # NB: We generate a new "run id" per iteration of the loop in order to allow us to
            # observe fresh values for Goals. See notes in `scheduler.rs`.
            session.scheduler_session.new_run_id()
            try:
                exit_code = self._body(session, options, options_bootstrapper, specs, v2, poll=True)
            except ExecutionError as e:
                self._logger.warning(e)
            iterations -= 1

        return exit_code

    def _body(
        self,
        session: LegacyGraphSession,
        options: Options,
        options_bootstrapper: OptionsBootstrapper,
        specs: Specs,
        v2: bool,
        poll: bool,
    ) -> int:
        exit_code = PANTS_SUCCEEDED_EXIT_CODE

        _, ambiguous_goals, v2_goals = options.goals_by_version

        if v2_goals or (ambiguous_goals and v2):
            goals = v2_goals + (ambiguous_goals if v2 else tuple())

            # When polling we use a delay (only applied in cases where we have waited for something
            # to do) in order to avoid re-running too quickly when changes arrive in clusters.
            exit_code = session.run_goal_rules(
                options_bootstrapper=options_bootstrapper,
                union_membership=self._union_membership,
                options=options,
                goals=goals,
                specs=specs,
                poll=poll,
                poll_delay=(0.1 if poll else None),
            )

        return exit_code

    def run(self):
        """Main service entrypoint."""
        while not self._state.is_terminating:
            self._state.maybe_pause()
            self._check_invalidation_watcher_liveness()
            # NB: This is a long poll that will keep us from looping too quickly here.
            self._check_invalidation_globs(poll=True)
