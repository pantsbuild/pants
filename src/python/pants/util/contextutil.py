# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from queue import Queue
from socketserver import TCPServer
from types import FrameType
from typing import IO, Any, Callable, Iterator, Mapping, Optional, Type, Union, cast

from colors import green

from pants.util.dirutil import safe_delete
from pants.util.tarutil import TarFile


class InvalidZipPath(ValueError):
    """Indicates a bad zip file path."""


@contextmanager
def environment_as(**kwargs: Optional[str]) -> Iterator[None]:
    """Update the environment to the supplied values, for example:

    with environment_as(PYTHONPATH='foo:bar:baz',
                        PYTHON='/usr/bin/python2.7'):
      subprocess.Popen(foo).wait()
    """
    new_environment = kwargs
    old_environment = {}

    def setenv(key: str, val: Optional[str]) -> None:
        if val is not None:
            os.environ[key] = val
        else:
            if key in os.environ:
                del os.environ[key]

    for key, val in new_environment.items():
        old_environment[key] = os.environ.get(key)
        setenv(key, val)
    try:
        yield
    finally:
        for key, val in old_environment.items():
            setenv(key, val)


def _purge_env() -> None:
    # N.B. Without the use of `del` here (which calls `os.unsetenv` under the hood), subprocess
    # invokes or other things that may access the environment at the C level may not see the
    # correct env vars (i.e. we can't just replace os.environ with an empty dict).
    # See https://docs.python.org/3/library/os.html#os.unsetenv for more info.
    #
    # Wraps iterable in list() to make a copy and avoid issues with deleting while iterating.
    for k in list(os.environ.keys()):
        del os.environ[k]


def _restore_env(env: Mapping[str, str]) -> None:
    for k, v in env.items():
        os.environ[k] = v


@contextmanager
def hermetic_environment_as(**kwargs: Optional[str]) -> Iterator[None]:
    """Set the environment to the supplied values from an empty state."""
    old_environment = os.environ.copy()
    _purge_env()
    try:
        with environment_as(**kwargs):
            yield
    finally:
        _purge_env()
        _restore_env(old_environment)


@contextmanager
def _stdio_stream_as(src_fd: int, dst_fd: int, dst_sys_attribute: str, mode: str) -> Iterator[None]:
    """Replace the given dst_fd and attribute on `sys` with an open handle to the given src_fd."""
    if src_fd == -1:
        src = open("/dev/null", mode)
        src_fd = src.fileno()

    # Capture the python and os level file handles.
    old_dst = getattr(sys, dst_sys_attribute)
    old_dst_fd = os.dup(dst_fd)
    if src_fd != dst_fd:
        os.dup2(src_fd, dst_fd)

    # Open up a new file handle to temporarily replace the python-level io object, then yield.
    new_dst = os.fdopen(dst_fd, mode)
    setattr(sys, dst_sys_attribute, new_dst)
    try:
        yield
    finally:
        new_dst.close()

        # Restore the python and os level file handles.
        os.dup2(old_dst_fd, dst_fd)
        setattr(sys, dst_sys_attribute, old_dst)


@contextmanager
def stdio_as(stdout_fd: int, stderr_fd: int, stdin_fd: int) -> Iterator[None]:
    """Redirect sys.{stdout, stderr, stdin} to alternate file descriptors.

    As a special case, if a given destination fd is `-1`, we will replace it with an open file handle
    to `/dev/null`.

    NB: If the filehandles for sys.{stdout, stderr, stdin} have previously been closed, it's
    possible that the OS has repurposed fds `0, 1, 2` to represent other files or sockets. It's
    impossible for this method to locate all python objects which refer to those fds, so it's up
    to the caller to guarantee that `0, 1, 2` are safe to replace.

    The streams expect unicode. To write and read bytes, access their buffer, e.g. `stdin.buffer.read()`.
    """
    with _stdio_stream_as(stdin_fd, 0, "stdin", "r"), _stdio_stream_as(
        stdout_fd, 1, "stdout", "w"
    ), _stdio_stream_as(stderr_fd, 2, "stderr", "w"):
        yield


@contextmanager
def signal_handler_as(
    sig: int, handler: Union[int, Callable[[int, FrameType], None]]
) -> Iterator[None]:
    """Temporarily replaces a signal handler for the given signal and restores the old handler.

    :param sig: The target signal to replace the handler for (e.g. signal.SIGINT).
    :param handler: The new temporary handler.
    """
    old_handler = signal.signal(sig, handler)
    try:
        yield
    finally:
        signal.signal(sig, old_handler)


@contextmanager
def temporary_dir(
    root_dir: Optional[str] = None,
    cleanup: bool = True,
    suffix: Optional[str] = None,
    permissions: Optional[int] = None,
    prefix: Optional[str] = tempfile.template,
) -> Iterator[str]:
    """A with-context that creates a temporary directory.

    :API: public

    You may specify the following keyword args:
    :param root_dir: The parent directory to create the temporary directory.
    :param cleanup: Whether or not to clean up the temporary directory.
    :param permissions: If provided, sets the directory permissions to this mode.
    """
    path = tempfile.mkdtemp(dir=root_dir, suffix=suffix, prefix=prefix)

    try:
        if permissions is not None:
            os.chmod(path, permissions)
        yield path
    finally:
        if cleanup:
            shutil.rmtree(path, ignore_errors=True)


@contextmanager
def temporary_file_path(
    root_dir: Optional[str] = None,
    cleanup: bool = True,
    suffix: Optional[str] = None,
    permissions: Optional[int] = None,
) -> Iterator[str]:
    """A with-context that creates a temporary file and returns its path.

    :API: public

    You may specify the following keyword args:
    :param root_dir: The parent directory to create the temporary file.
    :param cleanup: Whether or not to clean up the temporary file.
    """
    with temporary_file(root_dir, cleanup=cleanup, suffix=suffix, permissions=permissions) as fd:
        fd.close()
        yield fd.name


@contextmanager
def temporary_file(
    root_dir: Optional[str] = None,
    cleanup: bool = True,
    suffix: Optional[str] = None,
    permissions: Optional[int] = None,
    binary_mode: bool = True,
) -> Iterator[IO]:
    """A with-context that creates a temporary file and returns a writeable file descriptor to it.

    You may specify the following keyword args:
    :param root_dir: The parent directory to create the temporary file.
    :param cleanup: Whether or not to clean up the temporary file.
    :param suffix: If suffix is specified, the file name will end with that suffix.
                       Otherwise there will be no suffix.
                       mkstemp() does not put a dot between the file name and the suffix;
                       if you need one, put it at the beginning of suffix.
                       See :py:class:`tempfile.NamedTemporaryFile`.
    :param permissions: If provided, sets the file to use these permissions.
    :param binary_mode: Whether file opens in binary or text mode.
    """
    mode = "w+b" if binary_mode else "w+"  # tempfile's default is 'w+b'
    with tempfile.NamedTemporaryFile(suffix=suffix, dir=root_dir, delete=False, mode=mode) as fd:
        try:
            if permissions is not None:
                os.chmod(fd.name, permissions)
            yield fd
        finally:
            if cleanup:
                safe_delete(fd.name)


@contextmanager
def safe_file(path: str, suffix: Optional[str] = None, cleanup: bool = True) -> Iterator[str]:
    """A with-context that copies a file, and copies the copy back to the original file on success.

    This is useful for doing work on a file but only changing its state on success.

    :param suffix: Use this suffix to create the copy. Otherwise use a random string.
    :param cleanup: Whether or not to clean up the copy.
    """
    safe_path = f"{path}.{(suffix or uuid.uuid4())}"
    if os.path.exists(path):
        shutil.copy(path, safe_path)
    try:
        yield safe_path
        if cleanup:
            shutil.move(safe_path, path)
        else:
            shutil.copy(safe_path, path)
    finally:
        if cleanup:
            safe_delete(safe_path)


@contextmanager
def pushd(directory: str) -> Iterator[str]:
    """A with-context that encapsulates pushd/popd."""
    cwd = os.getcwd()
    os.chdir(directory)
    try:
        yield directory
    finally:
        os.chdir(cwd)


@contextmanager
def open_zip(path_or_file: Union[str, Any], *args, **kwargs) -> Iterator[zipfile.ZipFile]:
    """A with-context for zip files.

    Passes through *args and **kwargs to zipfile.ZipFile.

    :API: public

    :param path_or_file: Full path to zip file.
    :param args: Any extra args accepted by `zipfile.ZipFile`.
    :param kwargs: Any extra keyword args accepted by `zipfile.ZipFile`.
    :raises: `InvalidZipPath` if path_or_file is invalid.
    :raises: `zipfile.BadZipfile` if zipfile.ZipFile cannot open a zip at path_or_file.
    """
    if not path_or_file:
        raise InvalidZipPath(f"Invalid zip location: {path_or_file}")
    if "allowZip64" not in kwargs:
        kwargs["allowZip64"] = True
    try:
        zf = zipfile.ZipFile(path_or_file, *args, **kwargs)
    except zipfile.BadZipfile as bze:
        # Use the realpath in order to follow symlinks back to the problem source file.
        raise zipfile.BadZipfile(f"Bad Zipfile {os.path.realpath(path_or_file)}: {bze}")
    try:
        yield zf
    finally:
        zf.close()


@contextmanager
def open_tar(path_or_file: Union[str, Any], *args, **kwargs) -> Iterator[TarFile]:
    """A with-context for tar files.  Passes through positional and kwargs to tarfile.open.

    If path_or_file is a file, caller must close it separately.
    """
    (path, fileobj) = (
        (path_or_file, None) if isinstance(path_or_file, str) else (None, path_or_file)
    )
    kwargs["fileobj"] = fileobj
    with closing(TarFile.open(path, *args, **kwargs)) as tar:
        # We must cast the normal tarfile.TarFile to our custom pants.util.tarutil.TarFile.
        typed_tar = cast(TarFile, tar)
        yield typed_tar


class Timer:
    """Very basic with-context to time operations.

  Example usage:
    >>> from pants.util.contextutil import Timer
    >>> with Timer() as timer:
    ...   time.sleep(2)
    ...
    >>> timer.elapsed
    2.0020849704742432
    """

    def __init__(self, clock=time) -> None:
        self._clock = clock

    def __enter__(self) -> "Timer":
        self.start: float = self._clock.time()
        self.finish: Optional[float] = None
        return self

    @property
    def elapsed(self) -> float:
        end_time: float = self.finish if self.finish is not None else self._clock.time()
        return end_time - self.start

    def __exit__(self, typ, val, traceback):
        self.finish = self._clock.time()


@contextmanager
def exception_logging(logger: logging.Logger, msg: str) -> Iterator[None]:
    """Provides exception logging via `logger.exception` for a given block of code.

    :param logger: The `Logger` instance to use for logging.
    :param msg: The message to emit before `logger.exception` emits the traceback.
    """
    try:
        yield
    except Exception:
        logger.exception(msg)
        raise


@contextmanager
def maybe_profiled(profile_path: Optional[str]) -> Iterator[None]:
    """A profiling context manager.

    :param profile_path: The path to write profile information to. If `None`, this will no-op.
    """
    if not profile_path:
        yield
        return

    import cProfile

    profiler = cProfile.Profile()
    try:
        profiler.enable()
        yield
    finally:
        profiler.disable()
        profiler.dump_stats(profile_path)
        view_cmd = green(
            "gprof2dot -f pstats {path} | dot -Tpng -o {path}.png && open {path}.png".format(
                path=profile_path
            )
        )
        logging.getLogger().info(
            f"Dumped profile data to: {profile_path}\nUse e.g. {view_cmd} to render and view."
        )


@contextmanager
def http_server(handler_class: Type) -> Iterator[int]:
    def serve(port_queue: "Queue[int]", shutdown_queue: "Queue[bool]") -> None:
        httpd = TCPServer(("", 0), handler_class)
        httpd.timeout = 0.1
        port_queue.put(httpd.server_address[1])
        while shutdown_queue.empty():
            httpd.handle_request()

    port_queue: "Queue[int]" = Queue()
    shutdown_queue: "Queue[bool]" = Queue()
    t = threading.Thread(target=lambda: serve(port_queue, shutdown_queue))
    t.daemon = True
    t.start()

    try:
        yield port_queue.get(block=True)
    finally:
        shutdown_queue.put(True)
        t.join()
