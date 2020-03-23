# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

from pants.base.exception_sink import ExceptionSink
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest
from pants.engine.rules import RootRule, side_effecting

if TYPE_CHECKING:
    from pants.engine.scheduler import SchedulerSession


@dataclass(frozen=True)
class InteractiveProcessResult:
    process_exit_code: int


@dataclass(frozen=True)
class InteractiveProcessRequest:
    argv: Tuple[str, ...]
    env: Tuple[str, ...] = ()
    input_files: Digest = EMPTY_DIRECTORY_DIGEST
    run_in_workspace: bool = False

    def __post_init__(self):
        if self.input_files != EMPTY_DIRECTORY_DIGEST and self.run_in_workspace:
            raise ValueError(
                "InteractiveProessRequest should use the Workspace API to materialize any needed files when it runs in the workspace"
            )


@side_effecting
@dataclass(frozen=True)
class InteractiveRunner:
    _scheduler: "SchedulerSession"

    def run_local_interactive_process(
        self, request: InteractiveProcessRequest
    ) -> InteractiveProcessResult:
        ExceptionSink.toggle_ignoring_sigint_v2_engine(True)
        return self._scheduler.run_local_interactive_process(request)


def create_interactive_runner_rules():
    return [RootRule(InteractiveRunner)]
