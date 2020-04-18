# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import http.client
import logging
import os
import sys
import warnings
from logging import LogRecord, StreamHandler
from typing import List, Optional, TextIO

import pants.util.logging as pants_logging
from pants.base.exception_sink import ExceptionSink
from pants.engine.native import Native
from pants.util.dirutil import safe_mkdir
from pants.util.logging import LogLevel

# Although logging supports the WARN level, its not documented and could conceivably be yanked.
# Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
# setup a 'WARN' logging level name that maps to 'WARNING'.
logging.addLevelName(logging.WARNING, "WARN")
logging.addLevelName(pants_logging.TRACE, "TRACE")


def init_rust_logger(log_level: LogLevel, log_show_rust_3rdparty: bool) -> None:
    native = Native()
    native.init_rust_logging(log_level.level, log_show_rust_3rdparty)


class NativeHandler(StreamHandler):
    """This class is installed as a Python logging module handler (using  the logging.addHandler
    method) and proxies logs to the Rust logging infrastructure."""

    def __init__(
        self,
        log_level: LogLevel,
        stream: Optional[TextIO] = None,
        native_filename: Optional[str] = None,
    ):
        super().__init__(stream)

        if stream is not None and native_filename is not None:
            raise RuntimeError("NativeHandler must output to either a stream or a file, not both")

        self.native = Native()
        self.native_filename = native_filename
        self.setLevel(log_level.level)
        if stream:
            try:
                native = Native()
                native.setup_stderr_logger(log_level.level)
            except Exception as e:
                print(f"Error setting up pantsd logger: {e!r}", file=sys.stderr)
                raise e

    def emit(self, record: LogRecord) -> None:
        self.native.write_log(
            self.format(record), record.levelno, f"{record.name}:pid={os.getpid()}"
        )

    def flush(self) -> None:
        self.native.flush_log()

    def __repr__(self) -> str:
        return (
            f"NativeHandler(id={id(self)}, level={self.level}, filename={self.native_filename}, "
            f"stream={self.stream})"
        )


def _common_logging_setup(level: LogLevel, warnings_filter_regexes: Optional[List[str]]) -> None:
    def trace_fn(self, message, *args, **kwargs):
        if self.isEnabledFor(LogLevel.TRACE.level):
            self._log(LogLevel.TRACE.level, message, *args, **kwargs)

    logging.Logger.trace = trace_fn  # type: ignore[attr-defined]

    logger = logging.getLogger(None)
    for handler in logger.handlers:
        logger.removeHandler(handler)

    level.set_level_for(logger)

    # This routes warnings through our loggers instead of straight to raw stderr.
    logging.captureWarnings(True)

    for message_regexp in warnings_filter_regexes or ():
        warnings.filterwarnings(action="ignore", message=message_regexp)

    if logger.isEnabledFor(LogLevel.TRACE.level):
        http.client.HTTPConnection.debuglevel = 1  # type: ignore[attr-defined]
        requests_logger = logging.getLogger("requests.packages.urllib3")
        LogLevel.TRACE.set_level_for(requests_logger)
        requests_logger.propagate = True


def setup_logging_to_stderr(
    level: LogLevel, *, warnings_filter_regexes: Optional[List[str]] = None
) -> None:
    """Sets up Python logging to stderr, proxied to Rust via a NativeHandler.

    We deliberately set the most verbose logging possible (i.e. the TRACE log level), here, and let
    the Rust logging faculties take care of filtering.
    """
    _common_logging_setup(level, warnings_filter_regexes)

    python_logger = logging.getLogger(None)
    handler = NativeHandler(level, stream=sys.stderr)
    python_logger.addHandler(handler)
    LogLevel.TRACE.set_level_for(python_logger)


def setup_logging_to_file(
    level: LogLevel,
    *,
    log_dir: str,
    log_filename: str = "pants.log",
    warnings_filter_regexes: Optional[List[str]] = None,
) -> NativeHandler:
    native = Native()
    logger = logging.getLogger(None)

    _common_logging_setup(level, warnings_filter_regexes)

    safe_mkdir(log_dir)
    log_path = os.path.join(log_dir, log_filename)

    fd = native.setup_pantsd_logger(log_path, level.level)
    ExceptionSink.reset_interactive_output_stream(os.fdopen(os.dup(fd), "a"))
    native_handler = NativeHandler(level, native_filename=log_path)

    logger.addHandler(native_handler)
    return native_handler
