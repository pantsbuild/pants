# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import http.client
import logging
import os
import sys
import warnings
from logging import Formatter, Handler, LogRecord, StreamHandler
from typing import List, Optional, TextIO, Tuple

import pants.util.logging as pants_logging
from pants.base.exception_sink import ExceptionSink
from pants.engine.internals.native import Native
from pants.util.dirutil import safe_mkdir
from pants.util.logging import LogLevel

# Although logging supports the WARN level, its not documented and could conceivably be yanked.
# Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
# setup a 'WARN' logging level name that maps to 'WARNING'.
logging.addLevelName(logging.WARNING, "WARN")
logging.addLevelName(pants_logging.TRACE, "TRACE")


def init_rust_logger(log_level: LogLevel, log_show_rust_3rdparty: bool) -> None:
    Native().init_rust_logging(log_level.level, log_show_rust_3rdparty)


class NativeHandler(StreamHandler):
    """This class is installed as a Python logging module handler (using  the logging.addHandler
    method) and proxies logs to the Rust logging infrastructure."""

    def __init__(
        self,
        log_level: LogLevel,
        stream: Optional[TextIO] = None,
        native_filename: Optional[str] = None,
    ):

        if stream is not None and native_filename is not None:
            raise RuntimeError("NativeHandler must output to either a stream or a file, not both")

        super().__init__(stream)
        self.native = Native()
        self.native_filename = native_filename
        self.setLevel(log_level.level)

        if stream:
            try:
                self.native.setup_stderr_logger(log_level.level)
            except Exception as e:
                print(f"Error setting up pantsd logger: {e!r}", file=sys.stderr)
                raise e

    def emit(self, record: LogRecord) -> None:
        self.native.write_log(
            msg=self.format(record), level=record.levelno, target=f"{record.name}:pid={os.getpid()}"
        )

    def flush(self) -> None:
        self.native.flush_log()

    def __repr__(self) -> str:
        return (
            f"NativeHandler(id={id(self)}, level={self.level}, filename={self.native_filename}, "
            f"stream={self.stream})"
        )


class ExceptionFormatter(Formatter):
    """Uses the `--print-exception-stacktrace` option to decide whether to render stacktraces."""

    def formatException(self, exc_info):
        if ExceptionSink.should_print_exception_stacktrace:
            return super().formatException(exc_info)
        return "\n(Use --print-exception-stacktrace to see more error details.)"


def clear_logging_handlers():
    logger = logging.getLogger(None)
    for handler in get_logging_handlers():
        logger.removeHandler(handler)


def get_logging_handlers() -> Tuple[Handler, ...]:
    logger = logging.getLogger(None)
    return tuple(logger.handlers)


def set_logging_handlers(handlers: Tuple[Handler, ...]):
    clear_logging_handlers()
    logger = logging.getLogger(None)
    for handler in handlers:
        logger.addHandler(handler)


def _common_logging_setup(level: LogLevel, warnings_filter_regexes: Optional[List[str]]) -> None:
    def trace_fn(self, message, *args, **kwargs):
        if self.isEnabledFor(LogLevel.TRACE.level):
            self._log(LogLevel.TRACE.level, message, *args, **kwargs)

    logging.Logger.trace = trace_fn  # type: ignore[attr-defined]
    logger = logging.getLogger(None)

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


def setup_logging(global_bootstrap_options):
    """Sets up logging for a pants run.

    This is called in two contexts: 1) PantsRunner, 2) DaemonPantsRunner. In the latter case, the
    loggers are saved and restored around this call, so in both cases it runs with no handlers
    configured (and asserts so!).
    """
    if get_logging_handlers():
        raise AssertionError("setup_logging should not be called while Handlers are installed.")

    ignores = global_bootstrap_options.ignore_pants_warnings
    global_level = global_bootstrap_options.level
    level = LogLevel.ERROR if getattr(global_bootstrap_options, "quiet", False) else global_level
    log_dir = global_bootstrap_options.logdir

    Native().init_rust_logging(level.level, global_bootstrap_options.log_show_rust_3rdparty)
    setup_logging_to_stderr(level, warnings_filter_regexes=ignores)
    if log_dir:
        setup_logging_to_file(global_level, log_dir=log_dir, warnings_filter_regexes=ignores)


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
    handler.setFormatter(ExceptionFormatter())
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
    handler = NativeHandler(level, native_filename=log_path)

    logger.addHandler(handler)
    return handler
