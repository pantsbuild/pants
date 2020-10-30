# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import http.client
import logging
import os
import warnings
from logging import Formatter, Handler, LogRecord, StreamHandler
from typing import Dict, Iterable, Optional, Tuple

import pants.util.logging as pants_logging
from pants.engine.internals.native import Native
from pants.option.option_value_container import OptionValueContainer
from pants.util.dirutil import safe_mkdir
from pants.util.logging import LogLevel

# Although logging supports the WARN level, its not documented and could conceivably be yanked.
# Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
# setup a 'WARN' logging level name that maps to 'WARNING'.
logging.addLevelName(logging.WARNING, "WARN")
logging.addLevelName(pants_logging.TRACE, "TRACE")


def init_rust_logger(
    log_level: LogLevel,
    log_show_rust_3rdparty: bool,
    use_color: bool,
    show_target: bool,
    log_levels_by_target: Dict[str, LogLevel] = {},
) -> None:
    Native().init_rust_logging(
        log_level.level, log_show_rust_3rdparty, use_color, show_target, log_levels_by_target
    )


def setup_warning_filtering(warnings_filter_regexes: Iterable[str]) -> None:
    """Sets up regex-based ignores for messages using the Python warnings system."""

    warnings.resetwarnings()
    for message_regexp in warnings_filter_regexes or ():
        warnings.filterwarnings(action="ignore", message=message_regexp)


class NativeHandler(StreamHandler):
    """This class is installed as a Python logging module handler (using the logging.addHandler
    method) and proxies logs to the Rust logging infrastructure."""

    def __init__(self, log_level: LogLevel, native_filename: Optional[str] = None) -> None:
        super().__init__(None)
        self.native = Native()
        self.native_filename = native_filename
        self.setLevel(pants_logging.TRACE)
        if not self.native_filename:
            self.native.setup_stderr_logger()

    def emit(self, record: LogRecord) -> None:
        self.native.write_log(msg=self.format(record), level=record.levelno, target=record.name)

    def flush(self) -> None:
        self.native.flush_log()

    def __repr__(self) -> str:
        return f"NativeHandler(id={id(self)}, level={self.level}, filename={self.native_filename}"


class ExceptionFormatter(Formatter):
    """Uses the `--print-stacktrace` option to decide whether to render stacktraces."""

    def __init__(self, print_stacktrace: bool):
        super().__init__(None)
        self.print_stacktrace = print_stacktrace

    def formatException(self, exc_info):
        if self.print_stacktrace:
            return super().formatException(exc_info)
        return "\n(Use --print-stacktrace to see more error details.)"


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


def _common_logging_setup(level: LogLevel) -> None:
    def trace_fn(self, message, *args, **kwargs):
        if self.isEnabledFor(LogLevel.TRACE.level):
            self._log(LogLevel.TRACE.level, message, *args, **kwargs)

    logging.Logger.trace = trace_fn  # type: ignore[attr-defined]
    logger = logging.getLogger(None)

    level.set_level_for(logger)
    # This routes warnings through our loggers instead of straight to raw stderr.
    logging.captureWarnings(True)

    if logger.isEnabledFor(LogLevel.TRACE.level):
        http.client.HTTPConnection.debuglevel = 1  # type: ignore[attr-defined]
        requests_logger = logging.getLogger("requests.packages.urllib3")
        LogLevel.TRACE.set_level_for(requests_logger)
        requests_logger.propagate = True


def setup_logging(global_bootstrap_options: OptionValueContainer, stderr_logging: bool) -> None:
    """Sets up logging for a Pants run.

    This is called in two contexts: 1) PantsRunner, 2) DaemonPantsRunner. In the latter case, the
    loggers are saved and restored around this call, so in both cases it runs with no handlers
    configured (and asserts so!).
    """
    if get_logging_handlers():
        raise AssertionError("setup_logging should not be called while Handlers are installed.")

    global_level = global_bootstrap_options.level
    log_dir = global_bootstrap_options.logdir

    log_show_rust_3rdparty = global_bootstrap_options.log_show_rust_3rdparty
    use_color = global_bootstrap_options.colors
    show_target = global_bootstrap_options.show_log_target
    log_levels_by_target = get_log_levels_by_target(global_bootstrap_options)

    init_rust_logger(
        global_level, log_show_rust_3rdparty, use_color, show_target, log_levels_by_target
    )

    if stderr_logging:
        setup_logging_to_stderr(global_level, global_bootstrap_options.print_stacktrace)

    if log_dir:
        setup_logging_to_file(global_level, log_dir=log_dir)


def get_log_levels_by_target(global_bootstrap_options: OptionValueContainer) -> Dict[str, LogLevel]:
    raw_levels = global_bootstrap_options.log_levels_by_target
    levels: Dict[str, LogLevel] = {}
    for key, value in raw_levels.items():
        if not isinstance(key, str):
            raise ValueError(
                "Keys for log_domain_levels must be strings, but was given the key: {key} with type {type(key)}."
            )
        if not isinstance(value, str):
            raise ValueError(
                "Values for log_domain_levels must be strings, but was given the value: {value} with type {type(value)}."
            )
        log_level = LogLevel[value.upper()]
        levels[key] = log_level
    return levels


def setup_logging_to_stderr(level: LogLevel, print_stacktrace: bool) -> None:
    """Sets up Python logging to stderr, proxied to Rust via a NativeHandler.

    We deliberately set the most verbose logging possible (i.e. the TRACE log level), here, and let
    the Rust logging faculties take care of filtering.
    """
    _common_logging_setup(level)

    python_logger = logging.getLogger(None)
    handler = NativeHandler(level)
    handler.setFormatter(ExceptionFormatter(print_stacktrace))
    python_logger.addHandler(handler)
    LogLevel.TRACE.set_level_for(python_logger)


def setup_logging_to_file(
    level: LogLevel,
    *,
    log_dir: str,
    log_filename: str = "pants.log",
) -> NativeHandler:
    native = Native()
    logger = logging.getLogger(None)

    _common_logging_setup(level)

    safe_mkdir(log_dir)
    log_path = os.path.join(log_dir, log_filename)

    native.setup_pantsd_logger(log_path)
    handler = NativeHandler(level, native_filename=log_path)

    logger.addHandler(handler)
    return handler
