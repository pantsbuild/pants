# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Tuple

from pants.base.exception_sink import ExceptionSink
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest
from pants.engine.rules import RootRule, side_effecting
from pants.util.meta import frozen_after_init

if TYPE_CHECKING:
    from pants.engine.scheduler import SchedulerSession


@dataclass(frozen=True)
class InteractiveProcessResult:
    __slots__ = ("process_exit_code",)

    process_exit_code: int


@frozen_after_init
@dataclass(unsafe_hash=True)
class InteractiveProcessRequest:
    __slots__ = ("_is_frozen", "argv", "env", "input_files", "run_in_workspace")

    argv: Tuple[str, ...]
    env: Tuple[str, ...]
    input_files: Digest
    run_in_workspace: bool

    def __init__(
        self,
        argv: Iterable[str],
        *,
        env: Iterable[str] = (),
        input_files: Digest = EMPTY_DIRECTORY_DIGEST,
        run_in_workspace: bool = False
    ):
        self.argv = tuple(argv)
        self.env = tuple(env)
        self.input_files = input_files
        self.run_in_workspace = run_in_workspace
        self.__post_init__()

    def __post_init__(self):
        if self.input_files != EMPTY_DIRECTORY_DIGEST and self.run_in_workspace:
            raise ValueError(
                "InteractiveProcessRequest should use the Workspace API to materialize any needed "
                "files when it runs in the workspace"
            )


@side_effecting
@dataclass(frozen=True)
class InteractiveRunner:
    __slots__ = ("_scheduler",)

    _scheduler: "SchedulerSession"

    def run_local_interactive_process(
        self, request: InteractiveProcessRequest
    ) -> InteractiveProcessResult:
        ExceptionSink.toggle_ignoring_sigint_v2_engine(True)
        return self._scheduler.run_local_interactive_process(request)


def create_interactive_runner_rules():
    return [RootRule(InteractiveRunner)]
