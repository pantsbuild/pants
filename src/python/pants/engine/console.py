# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from typing import Callable, Optional

from colors import blue, cyan, green, magenta, red, yellow

from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.rules import side_effecting


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
        the system stdout/stderr. If a SchedulerSession is set, any running UI will be torn down
        before stdio is rendered.
        """

        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._use_colors = use_colors
        self._session = session

    @property
    def stdout(self):
        if self._session:
            self._session.teardown_dynamic_ui()
        return self._stdout

    @property
    def stderr(self):
        if self._session:
            self._session.teardown_dynamic_ui()
        return self._stderr

    def write_stdout(self, payload: str) -> None:
        self.stdout.write(payload)

    def write_stderr(self, payload: str) -> None:
        self.stderr.write(payload)

    def print_stdout(self, payload: str, end: str = "\n") -> None:
        self.write_stdout(f"{payload}{end}")

    def print_stderr(self, payload: str, end: str = "\n") -> None:
        self.write_stderr(f"{payload}{end}")

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
