# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Tuple

from pants.base.exception_sink import ExceptionSink
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.rules import RootRule, side_effecting
from pants.util.meta import frozen_after_init

if TYPE_CHECKING:
    from pants.engine.internals.scheduler import SchedulerSession


@dataclass(frozen=True)
class InteractiveProcessResult:
    exit_code: int


@frozen_after_init
@dataclass(unsafe_hash=True)
class InteractiveProcess:
    argv: Tuple[str, ...]
    env: Tuple[str, ...]
    input_digest: Digest
    run_in_workspace: bool

    def __init__(
        self,
        argv: Iterable[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        input_digest: Digest = EMPTY_DIGEST,
        run_in_workspace: bool = False,
    ) -> None:
        """Request to run a subprocess in the foreground, similar to subprocess.run().

        Unlike `Process`, the result will not be cached.

        To run the process, request an `InteractiveRunner` in a `@goal_rule`, then run
        `interactive_runner.run_process()`.
        """
        self.argv = tuple(argv)
        self.env = tuple(itertools.chain.from_iterable((env or {}).items()))
        self.input_digest = input_digest
        self.run_in_workspace = run_in_workspace
        self.__post_init__()

    def __post_init__(self):
        if self.input_digest != EMPTY_DIGEST and self.run_in_workspace:
            raise ValueError(
                "InteractiveProcessRequest should use the Workspace API to materialize any needed "
                "files when it runs in the workspace"
            )


@side_effecting
@dataclass(frozen=True)
class InteractiveRunner:
    _scheduler: "SchedulerSession"

    def run_process(self, request: InteractiveProcess) -> InteractiveProcessResult:
        ExceptionSink.toggle_ignoring_sigint_v2_engine(True)
        return self._scheduler.run_local_interactive_process(request)


def rules():
    return [RootRule(InteractiveRunner)]
