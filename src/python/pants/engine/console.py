# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import sys
from typing import Callable, TextIO

from colors import blue, cyan, green, magenta, red, yellow

from pants.engine.engine_aware import SideEffecting
from pants.engine.internals.scheduler import SchedulerSession


class Console(SideEffecting):
    """Class responsible for writing text to the console while Pants is running.

    A SchedulerSession should always be set in production usage, in order to track side-effects, and
    tear down any running UI before stdio is rendered.
    """

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        use_colors: bool = True,
        session: SchedulerSession | None = None,
    ):
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._use_colors = use_colors
        self._session = session
        self._enforce_effects = self._session is not None

    @property
    def stdin(self) -> TextIO:
        if self._session:
            self.side_effected()
            self._session.teardown_dynamic_ui()
        return self._stdin

    @property
    def stdout(self) -> TextIO:
        if self._session:
            self.side_effected()
            self._session.teardown_dynamic_ui()
        return self._stdout

    @property
    def stderr(self) -> TextIO:
        if self._session:
            self.side_effected()
            self._session.teardown_dynamic_ui()
        return self._stderr

    def input(self, prompt: str | None = None) -> str:
        """Equivalent to the `input` builtin, but clears any running UI before rendering."""
        if prompt is not None:
            self.write_stdout(prompt)
        return self.stdin.readline().rstrip("\n")

    def write_stdout(self, payload: str) -> None:
        self.stdout.write(payload)

    def write_stderr(self, payload: str) -> None:
        self.stderr.write(payload)

    def print_stdout(self, payload: str, end: str = "\n") -> None:
        self.write_stdout(f"{payload}{end}")

    def print_stderr(self, payload: str, end: str = "\n") -> None:
        self.write_stderr(f"{payload}{end}")

    def flush(self) -> None:
        self._stdout.flush()
        self._stderr.flush()

    def sigil_succeeded(self) -> str:
        """Sigil for a successful item."""
        return self.green("✓")

    def sigil_succeeded_with_edits(self) -> str:
        """Sigil for a successful item which caused an edit to the workspace."""
        return self.yellow("+")

    def sigil_failed(self) -> str:
        """Sigil for a failed item."""
        return self.red("✕")

    def sigil_skipped(self) -> str:
        """Sigil for a skipped item."""
        return self.yellow("-")

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
