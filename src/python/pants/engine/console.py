# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from typing import Any, Callable, Optional

from colors import blue, cyan, green, magenta, red

from pants.engine.native import Native
from pants.engine.rules import side_effecting


# TODO this needs to be a file-like object/stream
class NativeWriter:
    def __init__(self, session: Any):
        self._native = Native()
        self._session = session._session

    def write(self, payload: str):
        raise NotImplementedError

    # TODO It's not clear yet what this function should do, it depends on how
    # EngineDisplay in Rust ends up handling text.
    def flush(self):
        pass


class NativeStdOut(NativeWriter):
    def write(self, payload):
        self._native.write_stdout(self._session, payload)


class NativeStdErr(NativeWriter):
    def write(self, payload):
        self._native.write_stderr(self._session, payload)


@side_effecting
class Console:
    """Class responsible for writing text to the console while Pants is running."""

    side_effecting = True

    def __init__(
        self, stdout=None, stderr=None, use_colors: bool = True, session: Optional[Any] = None
    ):
        """`stdout` and `stderr` may be explicitly provided when Console is constructed.

        We use this in tests to provide a mock we can write tests against, rather than writing to
        the system stdout/stderr. If they are not defined, the effective stdout/stderr are proxied
        to Rust engine intrinsic code if there is a scheduler session provided, or just written to
        the standard Python-provided stdout/stderr if it is None. A scheduler session is provided if
        --v2-ui is set.
        """

        has_scheduler = session is not None

        self._stdout = stdout or (NativeStdOut(session) if has_scheduler else sys.stdout)
        self._stderr = stderr or (NativeStdErr(session) if has_scheduler else sys.stderr)
        self._use_colors = use_colors

    @property
    def stdout(self):
        return self._stdout

    @property
    def stderr(self):
        return self._stderr

    def write_stdout(self, payload):
        self.stdout.write(payload)

    def write_stderr(self, payload):
        self.stderr.write(payload)

    def print_stdout(self, payload, end="\n"):
        print(payload, file=self.stdout, end=end)

    def print_stderr(self, payload, end="\n"):
        print(payload, file=self.stderr, end=end)

    def flush(self):
        self.stdout.flush()
        self.stderr.flush()

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
