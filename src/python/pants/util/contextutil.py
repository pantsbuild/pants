# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import shutil
import ssl
import sys
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from socketserver import TCPServer
from typing import IO, Any, Callable, Iterator, Mapping

from colors import green

from pants.util.dirutil import safe_delete


class InvalidZipPath(ValueError):
    """Indicates a bad zip file path."""


@contextmanager
def environment_as(**kwargs: str | None) -> Iterator[None]:
    """Update the environment to the supplied values, for example:

    with environment_as(PYTHONPATH='foo:bar:baz',
                        PYTHON='/usr/bin/python2.7'):
      subprocess.Popen(foo).wait()
    """
    new_environment = kwargs
    old_environment = {}

    def setenv(key: str, val: str | None) -> None:
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
def hermetic_environment_as(**kwargs: str | None) -> Iterator[None]:
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
def argv_as(args: tuple[str, ...]) -> Iterator[None]:
    """Temporarily set `sys.argv` to the supplied value."""
    old_args = sys.argv
    try:
        sys.argv = list(args)
        yield
    finally:
        sys.argv = old_args


@contextmanager
def temporary_dir(
    root_dir: str | None = None,
    cleanup: bool = True,
    suffix: str | None = None,
    permissions: int | None = None,
    prefix: str | None = tempfile.template,
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
    root_dir: str | None = None,
    cleanup: bool = True,
    suffix: str | None = None,
    permissions: int | None = None,
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
    root_dir: str | None = None,
    cleanup: bool = True,
    suffix: str | None = None,
    permissions: int | None = None,
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
def overwrite_file_content(
    file_path: str | Path,
    temporary_content: bytes | str | Callable[[bytes], bytes] | None = None,
) -> Iterator[None]:
    """A helper that resets a file after the method runs.

     It will read a file, save the content, maybe write temporary_content to it, yield, then
     write the original content to the file.

    :param file_path: Absolute path to the file to be reset after the method runs.
    :param temporary_content: Content to write to the file, or a function from current content
      to new temporary content.
    """
    file_path = Path(file_path)
    original_content = file_path.read_bytes()
    try:
        if temporary_content is not None:
            if callable(temporary_content):
                content = temporary_content(original_content)
            elif isinstance(temporary_content, bytes):
                content = temporary_content
            else:
                content = temporary_content.encode()
            file_path.write_bytes(content)
        yield
    finally:
        file_path.write_bytes(original_content)


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
def open_zip(path_or_file: str | Any, *args, **kwargs) -> Iterator[zipfile.ZipFile]:
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
def maybe_profiled(profile_path: str | None) -> Iterator[None]:
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
def http_server(handler_class: type, ssl_context: ssl.SSLContext | None = None) -> Iterator[int]:
    def serve(port_queue: Queue[int], shutdown_queue: Queue[bool]) -> None:
        httpd = TCPServer(("", 0), handler_class)
        httpd.timeout = 0.1
        if ssl_context:
            httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)

        port_queue.put(httpd.server_address[1])
        while shutdown_queue.empty():
            httpd.handle_request()

    port_queue: Queue[int] = Queue()
    shutdown_queue: Queue[bool] = Queue()
    t = threading.Thread(target=lambda: serve(port_queue, shutdown_queue))
    t.daemon = True
    t.start()

    try:
        yield port_queue.get(block=True)
    finally:
        shutdown_queue.put(True)
        t.join()
