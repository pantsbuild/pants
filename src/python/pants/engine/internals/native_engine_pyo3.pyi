# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from io import RawIOBase
from typing import TextIO

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

# ------------------------------------------------------------------------------------------
# Stdio
# ------------------------------------------------------------------------------------------

def maybe_set_panic_handler() -> None: ...
def write_log(msg: str, level: int, target: str) -> None: ...
def flush_log() -> None: ...
def set_per_run_log_path(path: str | None) -> None: ...
def stdio_initialize(
    level: int,
    show_rust_3rdparty_logs: bool,
    use_color: bool,
    show_target: bool,
    log_levels_by_target: dict[str, int],
    literal_filters: tuple[str, ...],
    regex_filters: tuple[str, ...],
    log_file: str,
) -> tuple[RawIOBase, TextIO, TextIO]: ...
def stdio_thread_console_set(stdin_fileno: int, stdout_fileno: int, stderr_fileno: int) -> None: ...
def stdio_thread_console_clear() -> None: ...

class PyStdioDestination:
    @classmethod
    def get_for_thread(cls) -> PyStdioDestination: ...
    def set_for_thread(self) -> None: ...

# ------------------------------------------------------------------------------------------
# Nailgun
# ------------------------------------------------------------------------------------------

class PyNailgunClient:
    def __init__(self, port: int, executor: PyExecutor) -> None: ...
    def execute(self, command: str, args: list[str], env: dict[str, str]) -> int: ...

class PantsdConnectionException(Exception):
    pass

class PantsdClientException(Exception):
    pass

# ------------------------------------------------------------------------------------------
# Testutil
# ------------------------------------------------------------------------------------------

class PyExecutor:
    def __init__(self, core_threads: int, max_threads: int) -> None: ...

class PyStubCASBuilder:
    def always_errors(self) -> PyStubCASBuilder: ...
    def build(self, executor: PyExecutor) -> PyStubCAS: ...

class PyStubCAS:
    @classmethod
    def builder(cls) -> PyStubCASBuilder: ...
    @property
    def address(self) -> str: ...
