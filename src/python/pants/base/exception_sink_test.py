# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import unittest.mock

import pytest

from pants.base.exception_sink import ExceptionSink
from pants.engine.platform import Platform
from pants.util.contextutil import temporary_dir
from pants.util.enums import match


def _gen_sink_subclass():
    # Avoid modifying global state by generating a subclass.
    class AnonymousSink(ExceptionSink):
        pass

    return AnonymousSink


def test_reset_log_location():
    sink = _gen_sink_subclass()
    with temporary_dir() as tmpdir:
        sink.reset_log_location(tmpdir)
        assert tmpdir == sink._log_dir


def test_set_invalid_log_location():
    assert os.path.isdir("/does/not/exist") is False
    sink = _gen_sink_subclass()
    with pytest.raises(ExceptionSink.ExceptionSinkError) as exc:
        sink.reset_log_location("/does/not/exist")
    assert (
        "The provided log location path at '/does/not/exist' is not writable or could not be "
        "created"
    ) in str(exc.value)

    # NB: This target is marked with 'platform_specific_behavior' because OSX errors out here at
    # creating a new directory with safe_mkdir(), Linux errors out trying to create the directory
    # for its log files with safe_open(). This may be due to differences in the filesystems.
    # TODO: figure out why we error out at different points here!
    with pytest.raises(ExceptionSink.ExceptionSinkError) as exc:
        sink.reset_log_location("/")
    err_str = {
        Platform.darwin: (
            "The provided log location path at '/' is not writable or could not be created: "
            "[Errno 21] Is a directory: '/'."
        ),
        Platform.linux: (
            "Error opening fatal error log streams for log location '/': [Errno 13] Permission "
            "denied: '/.pids'"
        ),
    }
    assert match(Platform.current, err_str) in str(exc.value)


def test_log_exception():
    sink = _gen_sink_subclass()

    with temporary_dir() as tmpdir:
        # Check that tmpdir exists, and log an exception into that directory.
        sink.reset_log_location(tmpdir)
        pid = os.getpid()

        with unittest.mock.patch(
            "setproctitle.getproctitle", autospec=True, spec_set=True
        ) as getproctitle_mock:
            getproctitle_mock.return_value = "fake_title"
            sink._log_exception("XXX")
            getproctitle_mock.assert_called_once()

        # This should have created two log files, one specific to the current pid.
        assert os.listdir(tmpdir) == [".pids"]

        cur_process_error_log_path = ExceptionSink.exceptions_log_path(for_pid=pid, in_dir=tmpdir)
        assert os.path.isfile(cur_process_error_log_path) is True

        shared_error_log_path = ExceptionSink.exceptions_log_path(in_dir=tmpdir)
        assert os.path.isfile(shared_error_log_path) is True
        # Ensure we're creating two separate files.
        assert cur_process_error_log_path != shared_error_log_path

        # We only logged a single error, so the files should both contain only that single log entry.
        err_rx = f"""\
timestamp: ([^\n]+)
process title: fake_title
sys.argv: ([^\n]+)
pid: {pid}
XXX
"""
        with open(cur_process_error_log_path, "r") as cur_pid_file:
            assert bool(re.search(err_rx, cur_pid_file.read()))
        with open(shared_error_log_path, "r") as shared_log_file:
            assert bool(re.search(err_rx, shared_log_file.read()))


def test_backup_logging_on_fatal_error(caplog):
    sink = _gen_sink_subclass()
    with temporary_dir() as tmpdir:
        sink.reset_log_location(tmpdir)
        with unittest.mock.patch.object(sink, "_try_write_with_flush", autospec=sink) as mock_write:
            mock_write.side_effect = ExceptionSink.ExceptionSinkError("fake write failure")
            sink._log_exception("XXX")

    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == 2

    def assert_log(log_file_type: str, log):
        assert bool(
            re.search(
                fr"Error logging the message 'XXX' to the {log_file_type} file handle for .* at "
                fr"pid {os.getpid()}",
                log.msg,
            )
        )
        assert log.filename == "exception_sink.py"

    assert_log("pid-specific", errors[0])
    assert_log("shared", errors[1])
