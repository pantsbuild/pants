# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import http.client
import locale
import logging
import sys
from contextlib import contextmanager
from io import BufferedReader, TextIOWrapper
from logging import Formatter, Handler, LogRecord
from pathlib import PurePath
from typing import Iterator

import pants.util.logging as pants_logging
from pants.engine.internals import native_engine
from pants.option.option_value_container import OptionValueContainer
from pants.util.dirutil import safe_mkdir_for
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import strip_prefix

# Although logging supports the WARN level, its not documented and could conceivably be yanked.
# Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
# setup a 'WARN' logging level name that maps to 'WARNING'.
logging.addLevelName(logging.WARNING, "WARN")
logging.addLevelName(pants_logging.TRACE, "TRACE")


class _NativeHandler(Handler):
    """This class is installed as a Python logging module handler (using the logging.addHandler
    method) and proxies logs to the Rust logging infrastructure."""

    def emit(self, record: LogRecord) -> None:
        native_engine.write_log(self.format(record), record.levelno, record.name)

    def flush(self) -> None:
        native_engine.flush_log()


class _ExceptionFormatter(Formatter):
    """Possibly render the stacktrace and possibly give debug hints, based on global options."""

    def __init__(self, level: LogLevel, *, print_stacktrace: bool) -> None:
        super().__init__(None)
        self.level = level
        self.print_stacktrace = print_stacktrace

    def formatException(self, exc_info):
        stacktrace = super().formatException(exc_info) if self.print_stacktrace else ""

        debug_instructions = []
        if not self.print_stacktrace:
            debug_instructions.append("--print-stacktrace for more error details")
        if self.level not in {LogLevel.DEBUG, LogLevel.TRACE}:
            debug_instructions.append("-ldebug for more logs")
        debug_instructions = (
            f"Use {' and/or '.join(debug_instructions)}. " if debug_instructions else ""
        )

        return (
            f"{stacktrace}\n\n{debug_instructions}\nSee {doc_url('troubleshooting')} for common "
            f"issues.\nConsider reaching out for help: {doc_url('getting-help')}\n"
        )


@contextmanager
def stdio_destination(stdin_fileno: int, stdout_fileno: int, stderr_fileno: int) -> Iterator[None]:
    """Sets a destination for both logging and stdio: must be called after `initialize_stdio`.

    After `initialize_stdio` and outside of this contextmanager, the default stdio destination is
    the pants.log. But inside of this block, all engine "tasks"/@rules that are spawned will have
    thread/task-local state that directs their IO to the given destination. When the contextmanager
    exits all tasks will be restored to the default destination (regardless of whether they have
    completed).
    """
    if not logging.getLogger(None).handlers:
        raise AssertionError("stdio_destination should only be called after initialize_stdio.")

    native_engine.stdio_thread_console_set(stdin_fileno, stdout_fileno, stderr_fileno)
    try:
        yield
    finally:
        native_engine.stdio_thread_console_clear()


def stdio_destination_use_color(use_color: bool) -> None:
    """Sets a color mode for the current thread's destination.

    True or false force color to be used or not used: None causes TTY detection to decide whether
    color will be used.

    NB: This method is independent from either `stdio_destination` or `initialize_stdio` because
    we cannot decide whether to use color for a particular destination until it is open AND we have
    parsed options for the relevant connection.
    """
    native_engine.stdio_thread_console_color_mode_set(use_color)


@contextmanager
def _python_logging_setup(
    level: LogLevel, log_levels_by_target: dict[str, LogLevel], *, print_stacktrace: bool
) -> Iterator[None]:
    """Installs a root Python logger that routes all logging through a Rust logger."""

    def trace_fn(self, message, *args, **kwargs):
        if self.isEnabledFor(LogLevel.TRACE.level):
            self._log(LogLevel.TRACE.level, message, *args, **kwargs)

    logging.Logger.trace = trace_fn  # type: ignore[attr-defined]
    logger = logging.getLogger(None)

    def clear_logging_handlers():
        handlers = tuple(logger.handlers)
        for handler in handlers:
            logger.removeHandler(handler)
        return handlers

    def set_logging_handlers(handlers):
        for handler in handlers:
            logger.addHandler(handler)

    # Remove existing handlers, and restore them afterward.
    handlers = clear_logging_handlers()
    try:
        # This routes warnings through our loggers instead of straight to raw stderr.
        logging.captureWarnings(True)
        handler = _NativeHandler()
        exc_formatter = _ExceptionFormatter(level, print_stacktrace=print_stacktrace)
        handler.setFormatter(exc_formatter)
        logger.addHandler(handler)
        level.set_level_for(logger)

        for key, level in log_levels_by_target.items():
            level.set_level_for(logging.getLogger(key))

        if logger.isEnabledFor(LogLevel.TRACE.level):
            http.client.HTTPConnection.debuglevel = 1
            requests_logger = logging.getLogger("requests.packages.urllib3")
            LogLevel.TRACE.set_level_for(requests_logger)
            requests_logger.propagate = True

        yield
    finally:
        clear_logging_handlers()
        set_logging_handlers(handlers)


@contextmanager
def initialize_stdio(global_bootstrap_options: OptionValueContainer) -> Iterator[None]:
    """Mutates sys.std* and logging to route stdio for a Pants process to thread local destinations.

    In this context, `sys.std*` and logging handlers will route through Rust code that uses
    thread-local information to decide whether to write to a file, or to stdio file handles.

    To control the stdio destination set by this method, use the `stdio_destination` context manager.

    This is called in two different processes:
    * PantsRunner, after it has determined that LocalPantsRunner will be running in process, and
      immediately before setting a `stdio_destination` for the remainder of the run.
    * PantsDaemon, immediately on startup. The process will then default to sending stdio to the log
      until client connections arrive, at which point `stdio_destination` is used per-connection.
    """
    with initialize_stdio_raw(
        global_bootstrap_options.level,
        global_bootstrap_options.log_show_rust_3rdparty,
        global_bootstrap_options.show_log_target,
        _get_log_levels_by_target(global_bootstrap_options),
        global_bootstrap_options.print_stacktrace,
        global_bootstrap_options.ignore_warnings,
        global_bootstrap_options.pants_workdir,
    ):
        yield


@contextmanager
def initialize_stdio_raw(
    global_level: LogLevel,
    log_show_rust_3rdparty: bool,
    show_target: bool,
    log_levels_by_target: dict[str, LogLevel],
    print_stacktrace: bool,
    ignore_warnings: list[str],
    pants_workdir: str,
) -> Iterator[None]:
    literal_filters = []
    regex_filters = []
    for filt in ignore_warnings:
        if filt.startswith("$regex$"):
            regex_filters.append(strip_prefix(filt, "$regex$"))
        else:
            literal_filters.append(filt)

    # Set the pants log destination.
    log_path = str(pants_log_path(PurePath(pants_workdir)))
    safe_mkdir_for(log_path)

    # Initialize thread-local stdio, and replace sys.std* with proxies.
    original_stdin, original_stdout, original_stderr = sys.stdin, sys.stdout, sys.stderr
    try:
        raw_stdin, sys.stdout, sys.stderr = native_engine.stdio_initialize(
            global_level.level,
            log_show_rust_3rdparty,
            show_target,
            {k: v.level for k, v in log_levels_by_target.items()},
            tuple(literal_filters),
            tuple(regex_filters),
            log_path,
        )
        sys.stdin = TextIOWrapper(
            BufferedReader(raw_stdin),
            # NB: We set the default encoding explicitly to bypass logic in the TextIOWrapper
            # constructor that would poke the underlying file (which is not valid until a
            # `stdio_destination` is set).
            encoding=locale.getpreferredencoding(False),
        )

        sys.__stdin__, sys.__stdout__, sys.__stderr__ = sys.stdin, sys.stdout, sys.stderr  # type: ignore[assignment]
        # Install a Python logger that will route through the Rust logger.
        with _python_logging_setup(
            global_level, log_levels_by_target, print_stacktrace=print_stacktrace
        ):
            yield
    finally:
        sys.stdin, sys.stdout, sys.stderr = original_stdin, original_stdout, original_stderr
        sys.__stdin__, sys.__stdout__, sys.__stderr__ = sys.stdin, sys.stdout, sys.stderr  # type: ignore[assignment]


def pants_log_path(workdir: PurePath) -> PurePath:
    """Given the path of the workdir, returns the `pants.log` path."""
    return workdir / "pants.log"


def _get_log_levels_by_target(
    global_bootstrap_options: OptionValueContainer,
) -> dict[str, LogLevel]:
    raw_levels = global_bootstrap_options.log_levels_by_target
    levels: dict[str, LogLevel] = {}
    for key, value in raw_levels.items():
        if not isinstance(key, str):
            raise ValueError(
                f"Keys for log_domain_levels must be strings, but was given the key: {key} with type {type(key)}."
            )
        if not isinstance(value, str):
            raise ValueError(
                f"Values for log_domain_levels must be strings, but was given the value: {value} with type {type(value)}."
            )
        log_level = LogLevel[value.upper()]
        levels[key] = log_level
    return levels
