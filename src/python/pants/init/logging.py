# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import http.client
import logging
import os
import sys
import warnings
from dataclasses import dataclass
from logging import Handler, Logger, LogRecord, StreamHandler
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


@dataclass(frozen=True)
class FileLoggingSetupResult:
    """A structured result for file logging setup."""

    log_handler: Handler


def init_rust_logger(log_level: LogLevel, log_show_rust_3rdparty: bool) -> None:
    native = Native()
    native.init_rust_logging(log_level.level, log_show_rust_3rdparty)


def setup_logging_to_stderr(python_logger: Logger, log_level: LogLevel) -> None:
    """We setup logging as loose as possible from the Python side, and let Rust do the filtering."""
    native = Native()
    handler = NativeHandler.create(log_level, native, stream=sys.stderr)
    python_logger.addHandler(handler)
    # Let the rust side filter levels; try to have the python side send everything to the rust logger.
    LogLevel.TRACE.set_level_for(python_logger)


class NativeHandler(StreamHandler):
    def __init__(
        self,
        log_level: LogLevel,
        native: Native,
        stream: Optional[TextIO] = None,
        native_filename: Optional[str] = None,
    ):
        super().__init__(stream)
        self.native = native
        self.native_filename = native_filename
        self.setLevel(log_level.level)

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

    @staticmethod
    def create(log_level: LogLevel, native: Native, stream: TextIO) -> "NativeHandler":
        try:
            native.setup_stderr_logger(log_level.level)
        except Exception as e:
            print(f"Error setting up pantsd logger: {e!r}", file=sys.stderr)
            raise e

        return NativeHandler(log_level, native, stream)


def create_native_pantsd_file_log_handler(
    log_level: LogLevel, native: Native, native_filename: str
) -> NativeHandler:
    fd = native.setup_pantsd_logger(native_filename, log_level.level)
    ExceptionSink.reset_interactive_output_stream(os.fdopen(os.dup(fd), "a"))
    return NativeHandler(log_level, native, native_filename=native_filename)


def setup_logging(
    log_level: LogLevel,
    *,
    log_dir: Optional[str],
    native: Native,
    console_stream: Optional[TextIO] = None,
    scope: Optional[str] = None,
    logfile_name: str = "pants.log",
    warnings_filter_regexes: Optional[List[str]] = None,
) -> Optional[FileLoggingSetupResult]:
    """Configures logging for a given scope, by default the global scope.

    :param log_level: The logging level to enable.
    :param native: An instance of the Native FFI lib, to register rust logging.
    :param console_stream: The stream to use for default (console) logging. If None (default), this
                           will disable console logging.
    :param log_dir: An optional directory to emit logs files in.  If unspecified, no disk logging
                    will occur.  If supplied, the directory will be created if it does not already
                    exist and all logs will be tee'd to a rolling set of log files in that
                    directory.
    :param scope: A logging scope to configure.  The scopes are hierarchichal logger names, with
                  The '.' separator providing the scope hierarchy.  By default the root logger is
                  configured.
    :param logfile_name: The base name of the log file (defaults to 'pants.log').

    :param warnings_filter_regexes: A series of regexes to ignore warnings for, typically from the
                                    `ignore_pants_warnings` option.
    :returns: The file logging setup configured if any.
    """

    # TODO(John Sirois): Consider moving to straight python logging.  The divide between the
    # context/work-unit logging and standard python logging doesn't buy us anything.

    # TODO(John Sirois): Support logging.config.fileConfig so a site can setup fine-grained
    # logging control and we don't need to be the middleman plumbing an option for each python
    # standard logging knob.

    # A custom log handler for sub-debug trace logging.
    def trace(self, message, *args, **kwargs):
        if self.isEnabledFor(LogLevel.TRACE.level):
            self._log(LogLevel.TRACE.level, message, *args, **kwargs)

    logging.Logger.trace = trace  # type: ignore[attr-defined]

    logger = logging.getLogger(scope)
    for handler in logger.handlers:
        logger.removeHandler(handler)

    if console_stream:
        native_handler = NativeHandler.create(log_level, native, stream=console_stream)
        logger.addHandler(native_handler)

    log_level.set_level_for(logger)

    # This routes warnings through our loggers instead of straight to raw stderr.
    logging.captureWarnings(True)

    for message_regexp in warnings_filter_regexes or ():
        warnings.filterwarnings(action="ignore", message=message_regexp)

    if logger.isEnabledFor(LogLevel.TRACE.level):
        http.client.HTTPConnection.debuglevel = 1  # type: ignore[attr-defined]
        requests_logger = logging.getLogger("requests.packages.urllib3")
        LogLevel.TRACE.set_level_for(requests_logger)
        requests_logger.propagate = True

    if not log_dir:
        return None

    safe_mkdir(log_dir)
    log_path = os.path.join(log_dir, logfile_name)

    native_handler = create_native_pantsd_file_log_handler(log_level, native, log_path)
    logger.addHandler(native_handler)
    return FileLoggingSetupResult(native_handler)
