# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import logging
import os
import socket
import sys
import time
from typing import Dict, List, Optional, cast

from pants.base.exiter import ExitCode
from pants.nailgun.nailgun_io import NailgunStreamWriter
from pants.nailgun.nailgun_protocol import ChunkType, MaybeShutdownSocket, NailgunProtocol
from pants.util.osutil import safe_kill
from pants.util.socket import RecvBufferedSocket
from pants.util.strutil import ensure_binary

logger = logging.getLogger(__name__)


class NailgunClientSession(NailgunProtocol, NailgunProtocol.TimeoutProvider):
    """Handles a single nailgun client session."""

    def __init__(self, sock, in_file, out_file, err_file, exit_on_broken_pipe=False):
        """
        :param bool exit_on_broken_pipe: whether or not to exit when `Broken Pipe` errors are
                    encountered
        """
        self._sock = sock
        self._input_writer = (
            None
            if not in_file
            else NailgunStreamWriter(
                (in_file.fileno(),), self._sock, (ChunkType.STDIN,), ChunkType.STDIN_EOF
            )
        )
        self._stdout = out_file
        self._stderr = err_file
        self._exit_on_broken_pipe = exit_on_broken_pipe
        # NB: These variables are set in a signal handler to implement graceful shutdown.
        self._exit_timeout_start_time = None
        self._exit_timeout = None
        self._exit_reason = None

    def _set_exit_timeout(self, timeout: float, reason: type) -> None:
        """Set a timeout for the remainder of the session, along with an exception to raise. which
        is implemented by NailgunProtocol.

        This method may be called by a signal handler to set a timeout for the remainder of the
        session. If the session completes before the timeout does, the exception in `reason` is
        raised. Otherwise, `NailgunProtocol.ProcessStreamTimeout` is raised.

        :param float timeout: The length of time to time out, in seconds.
        :param Exception reason: The exception to raise if the session completes before the timeout
                                 occurs.
        """
        self._exit_timeout_start_time = time.time()
        self._exit_timeout = timeout
        self._exit_reason = reason

    def maybe_timeout_options(self):
        """Implements the NailgunProtocol.TimeoutProvider interface."""
        if self._exit_timeout_start_time:
            return NailgunProtocol.TimeoutOptions(self._exit_timeout_start_time, self._exit_timeout)
        else:
            return None

    def _maybe_start_input_writer(self):
        if self._input_writer and not self._input_writer.is_alive():
            self._input_writer.start()

    def _maybe_stop_input_writer(self):
        if self._input_writer and self._input_writer.is_alive():
            self._input_writer.stop()
            self._input_writer.join()

    def _write_flush(self, fd, payload=None):
        """Write a payload to a given fd (if provided) and flush the fd."""
        try:
            if payload:
                fd.write(ensure_binary(payload))
            fd.flush()
        except (IOError, OSError) as e:
            # If a `Broken Pipe` is encountered during a stdio fd write, we're headless - bail.
            if e.errno == errno.EPIPE and self._exit_on_broken_pipe:
                sys.exit()
            # Otherwise, re-raise.
            raise

    class ExitTimedOut(Exception):
        """Raised when a timeout for the remote client exit was breached."""

    def _process_session(self):
        """Process the outputs of the nailgun session.

        :raises: :class:`NailgunProtocol.ProcessStreamTimeout` if a timeout set from a signal handler
                                                               with .set_exit_timeout() completes.
        :raises: :class:`Exception` if the session completes before the timeout, the `reason` argument
                                    to .set_exit_timeout() will be raised.
        """
        try:
            for chunk_type, payload in self.iter_chunks(
                MaybeShutdownSocket(self._sock),
                return_bytes=True,
                timeout_object=self,
            ):
                # TODO(#6579): assert that we have at this point received all the chunk types in
                # ChunkType.REQUEST_TYPES, and then allow any of ChunkType.EXECUTION_TYPES.
                if chunk_type == ChunkType.STDOUT:
                    self._write_flush(self._stdout, payload)
                elif chunk_type == ChunkType.STDERR:
                    self._write_flush(self._stderr, payload)
                elif chunk_type == ChunkType.EXIT:
                    self._write_flush(self._stdout)
                    self._write_flush(self._stderr)
                    return int(payload)
                elif chunk_type == ChunkType.START_READING_INPUT:
                    self._maybe_start_input_writer()
                else:
                    raise self.ProtocolError(
                        "received unexpected chunk {} -> {}".format(chunk_type, payload)
                    )
        except NailgunProtocol.ProcessStreamTimeout as e:
            logger.warning(
                "timed out when attempting to gracefully shut down the remote run. Sending SIGKILL"
                "message: {}".format(e)
            )
        finally:
            # Bad chunk types received from the server can throw NailgunProtocol.ProtocolError in
            # NailgunProtocol.iter_chunks(). This ensures the NailgunStreamWriter is always stopped.
            self._maybe_stop_input_writer()
            # If an asynchronous error was set at any point (such as in a signal handler), we want to make
            # sure we clean up the remote process before exiting with error.
            if self._exit_reason:
                raise self._exit_reason

    def execute(self, working_dir, main_class, *arguments, **environment):
        # Send the nailgun request.
        self.send_request(self._sock, working_dir, main_class, *arguments, **environment)

        # Process the remainder of the nailgun session.
        return self._process_session()


class NailgunClient:
    """A python nailgun client (see http://martiansoftware.com/nailgun for more info)."""

    class NailgunError(Exception):
        """Indicates an error interacting with a nailgun server."""

        DESCRIPTION = "Problem talking to nailgun server"

        _MSG_FMT = """\
{description} (address: {address}): {wrapped_exc!r}\
"""

        # TODO: preserve the traceback somehow!
        def __init__(self, address, wrapped_exc):
            self.address = address
            self.wrapped_exc = wrapped_exc

            msg = self._MSG_FMT.format(
                description=self.DESCRIPTION,
                address=self.address,
                wrapped_exc=self.wrapped_exc,
            )
            super(NailgunClient.NailgunError, self).__init__(msg, self.wrapped_exc)

    class NailgunConnectionError(NailgunError):
        """Indicates an error upon initial connect to the nailgun server."""

        DESCRIPTION = "Problem connecting to nailgun server"

    class NailgunExecutionError(NailgunError):
        """Indicates an error upon initial command execution on the nailgun server."""

        DESCRIPTION = "Problem executing command on nailgun server"

    # For backwards compatibility with nails expecting the ng c client special env vars.
    ENV_DEFAULTS = dict(NAILGUN_FILESEPARATOR=os.sep, NAILGUN_PATHSEPARATOR=os.pathsep)
    DEFAULT_NG_HOST = "127.0.0.1"
    DEFAULT_NG_PORT = 2113

    def __init__(
        self,
        host=None,
        port=None,
        ins=sys.stdin,
        out=None,
        err=None,
        exit_on_broken_pipe=False,
        metadata_base_dir=None,
        remote_pid=None,
    ):
        """Creates a nailgun client that can be used to issue zero or more nailgun commands.

        :param string host: the nailgun server to contact (defaults to '127.0.0.1')
        :param int port: the port the nailgun server is listening on (defaults to the default nailgun
                         port: 2113)
        :param file ins: a file to read command standard input from (defaults to stdin) - can be None
                         in which case no input is read
        :param file out: a stream to write command standard output to (defaults to stdout)
        :param file err: a stream to write command standard error to (defaults to stderr)
        :param bool exit_on_broken_pipe: whether or not to exit when `Broken Pipe` errors are
                                         encountered
        :param string metadata_base_dir: If a PID and PGRP are received from the server (only for
                                         pailgun connections), a file with the remote pid will be
                                         written under this directory. For non-pailgun connections this
                                         may be None.
        """
        self.remote_pid = remote_pid
        self._host = host or self.DEFAULT_NG_HOST
        self._port = port or self.DEFAULT_NG_PORT
        self._address = (self._host, self._port)
        self._address_string = ":".join(str(i) for i in self._address)
        self._stdin = ins
        self._stdout = out or sys.stdout.buffer
        self._stderr = err or sys.stderr.buffer
        self._exit_on_broken_pipe = exit_on_broken_pipe
        self._metadata_base_dir = metadata_base_dir
        # Mutable session state.
        self._session = None

    def try_connect(self):
        """Creates a socket, connects it to the nailgun and returns the connected socket.

        :returns: a connected `socket.socket`.
        :raises: `NailgunClient.NailgunConnectionError` on failure to connect.
        """
        sock = RecvBufferedSocket(
            sock=socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        )
        try:
            sock.connect(self._address)
        except (socket.error, socket.gaierror) as e:
            logger.debug(
                "Encountered socket exception {!r} when attempting connect to nailgun".format(e)
            )
            sock.close()
            raise self.NailgunConnectionError(
                address=self._address_string,
                wrapped_exc=e,
            )
        else:
            return sock

    def set_exit_timeout(self, timeout: float, reason: type) -> None:
        """Expose the inner session object's exit timeout setter."""
        self._session._set_exit_timeout(timeout, reason)

    def maybe_send_signal(self, signum):
        """Send the signal `signum`. No error is raised if the pid is None.

        :param signum: The signal number to send to the remote process.
        """
        if self.remote_pid is not None:
            safe_kill(self.remote_pid, signum)

    def execute(
        self,
        main_class: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> ExitCode:
        """Executes the given main_class with any supplied args in the given environment.

        :param main_class: the fully qualified class name of the main entrypoint
        :param args: any arguments to pass to the main entrypoint
        :param env: an env mapping made available to native nails via the nail context
        :param cwd: Set the working directory for this command
        :returns: the exit code of the main_class.
        :raises: :class:`NailgunClient.NailgunError` if there was an error during execution.
        """
        environment = dict(env or {})
        environment.update(self.ENV_DEFAULTS)
        cwd = cwd or os.getcwd()

        sock = self.try_connect()

        # TODO(#6579): NailgunClientSession currently requires callbacks because it can't depend on
        # having received these chunks, so we need to avoid clobbering these fields until we initialize
        # a new session.
        self._session = NailgunClientSession(
            sock=sock,
            in_file=self._stdin,
            out_file=self._stdout,
            err_file=self._stderr,
            exit_on_broken_pipe=self._exit_on_broken_pipe,
        )
        try:
            exit_code = self._session.execute(cwd, main_class, *args, **environment)
            return cast(ExitCode, exit_code)
        except (socket.error, NailgunProtocol.ProtocolError) as e:
            raise self.NailgunError(
                address=self._address_string,
                wrapped_exc=e,
            )
        finally:
            sock.close()
            self._session = None

    def __repr__(self):
        return "NailgunClient(host={!r}, port={!r})".format(self._host, self._port)
