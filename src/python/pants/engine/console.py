# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from dataclasses import dataclass
from typing import Callable, Optional, cast

from colors import blue, cyan, green, magenta, red, yellow

from pants.engine.internals.native import Native
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.rules import side_effecting


@dataclass(frozen=True)
class NativeWriter:
    scheduler_session: SchedulerSession
    native: Native = Native()

    def write(self, payload: str) -> None:
        raise NotImplementedError

    def flush(self):
        """flush() doesn't need to do anything for NativeWriter."""
        pass


class NativeStdOut(NativeWriter):
    def write(self, payload: str) -> None:
        scheduler = self.scheduler_session.scheduler._scheduler
        session = self.scheduler_session.session
        self.native.write_stdout(scheduler, session, payload, teardown_ui=True)


class NativeStdErr(NativeWriter):
    def write(self, payload: str) -> None:
        scheduler = self.scheduler_session.scheduler._scheduler
        session = self.scheduler_session.session
        self.native.write_stderr(scheduler, session, payload, teardown_ui=True)


@side_effecting
class Console:
    """Class responsible for writing text to the console while Pants is running."""

    side_effecting = True

    def __init__(
        self,
        stdout=None,
        stderr=None,
        use_colors: bool = True,
        session: Optional[SchedulerSession] = None,
    ):
        """`stdout` and `stderr` may be explicitly provided when Console is constructed.

        We use this in tests to provide a mock we can write tests against, rather than writing to
        the system stdout/stderr. If they are not defined, the effective stdout/stderr are proxied
        to Rust engine intrinsic code if there is a scheduler session provided, or just written to
        the standard Python-provided stdout/stderr if it is None. A scheduler session is provided if
        --dynamic-ui is set.
        """

        has_scheduler = session is not None

        self._stdout = stdout or (
            NativeStdOut(cast(SchedulerSession, session)) if has_scheduler else sys.stdout
        )
        self._stderr = stderr or (
            NativeStdErr(cast(SchedulerSession, session)) if has_scheduler else sys.stderr
        )
        self._use_colors = use_colors

    @property
    def stdout(self):
        return self._stdout

    @property
    def stderr(self):
        return self._stderr

    def write_stdout(self, payload: str) -> None:
        self.stdout.write(payload)

    def write_stderr(self, payload: str) -> None:
        self.stderr.write(payload)

    def print_stdout(self, payload: str, end: str = "\n") -> None:
        self.stdout.write(f"{payload}{end}")

    def print_stderr(self, payload: str, end: str = "\n") -> None:
        self.stderr.write(f"{payload}{end}")

    def flush(self) -> None:
        self.stdout.flush()
        self.stderr.flush()

    @property
    def use_colors(self):
        return self._use_colors

    def _safe_color(self, text: str, color: Callable[[str], str]) -> str:
        """We should only output color when the global flag --colors is enabled."""
        return color(text) if self._use_colors else text

    def blue(self, text: str) -> str:
        return self._safe_color(text, blue)

    def cyan(self, text: str) -> str:
        return self._safe_color(text, cyan)

    def green(self, text: str) -> str:
        return self._safe_color(text, green)

    def magenta(self, text: str) -> str:
        return self._safe_color(text, magenta)

    def red(self, text: str) -> str:
        return self._safe_color(text, red)

    def yellow(self, text: str) -> str:
        return self._safe_color(text, yellow)
