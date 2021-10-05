# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import glob
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, List, Mapping, Union

import pytest

from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.option.config import TomlSerializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient
from pants.testutil._process_handler import SubprocessProcessHandler
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_file_dump, safe_mkdir, safe_open
from pants.util.osutil import Pid
from pants.util.strutil import ensure_binary

# NB: If `shell=True`, it's a single `str`.
Command = Union[str, List[str]]


@dataclass(frozen=True)
class PantsResult:
    command: Command
    exit_code: int
    stdout: str
    stderr: str
    workdir: str
    pid: Pid

    def _format_unexpected_error_code_msg(self, msg: str | None) -> str:
        details = [msg] if msg else []
        details.append(" ".join(self.command))
        details.append(f"exit_code: {self.exit_code}")

        def indent(content):
            return "\n\t".join(content.splitlines())

        details.append(f"stdout:\n\t{indent(self.stdout)}")
        details.append(f"stderr:\n\t{indent(self.stderr)}")
        return "\n".join(details)

    def assert_success(self, msg: str | None = None) -> None:
        assert self.exit_code == 0, self._format_unexpected_error_code_msg(msg)

    def assert_failure(self, msg: str | None = None) -> None:
        assert self.exit_code != 0, self._format_unexpected_error_code_msg(msg)


@dataclass(frozen=True)
class PantsJoinHandle:
    command: Command
    process: subprocess.Popen
    workdir: str

    def join(self, stdin_data: bytes | str | None = None, tee_output: bool = False) -> PantsResult:
        """Wait for the pants process to complete, and return a PantsResult for it."""

        communicate_fn = self.process.communicate
        if tee_output:
            # TODO: MyPy complains that SubprocessProcessHandler.communicate_teeing_stdout_and_stderr does
            # not have the same type signature as subprocess.Popen.communicate_teeing_stdout_and_stderr.
            # It's possibly not worth trying to fix this because the type stubs for subprocess.Popen are
            # very complex and also not very precise, given how many different configurations Popen can
            # take.
            communicate_fn = SubprocessProcessHandler(self.process).communicate_teeing_stdout_and_stderr  # type: ignore[assignment]
        if stdin_data is not None:
            stdin_data = ensure_binary(stdin_data)
        (stdout, stderr) = communicate_fn(stdin_data)

        if self.process.returncode != PANTS_SUCCEEDED_EXIT_CODE:
            render_logs(self.workdir)

        return PantsResult(
            command=self.command,
            exit_code=self.process.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            workdir=self.workdir,
            pid=self.process.pid,
        )


def run_pants_with_workdir_without_waiting(
    command: Command,
    *,
    workdir: str,
    hermetic: bool = True,
    use_pantsd: bool = True,
    config: Mapping | None = None,
    extra_env: Mapping[str, str] | None = None,
    print_stacktrace: bool = True,
    **kwargs: Any,
) -> PantsJoinHandle:
    args = [
        "--no-pantsrc",
        f"--pants-workdir={workdir}",
        f"--print-stacktrace={print_stacktrace}",
    ]

    pantsd_in_command = "--no-pantsd" in command or "--pantsd" in command
    pantsd_in_config = config and "GLOBAL" in config and "pantsd" in config["GLOBAL"]
    if not pantsd_in_command and not pantsd_in_config:
        args.append("--pantsd" if use_pantsd else "--no-pantsd")

    if hermetic:
        args.append("--pants-config-files=[]")

    if config:
        toml_file_name = os.path.join(workdir, "pants.toml")
        with safe_open(toml_file_name, mode="w") as fp:
            fp.write(TomlSerializer(config).serialize())
        args.append(f"--pants-config-files={toml_file_name}")

    pants_script = [sys.executable, "-m", "pants"]

    # Permit usage of shell=True and string-based commands to allow e.g. `./pants | head`.
    pants_command: Command
    if kwargs.get("shell") is True:
        assert not isinstance(command, list), "must pass command as a string when using shell=True"
        pants_command = " ".join([*pants_script, " ".join(args), command])
    else:
        pants_command = [*pants_script, *args, *command]

    # Only allow-listed entries will be included in the environment if hermetic=True. Note that
    # the env will already be fairly hermetic thanks to the v2 engine; this provides an
    # additional layer of hermiticity.
    if hermetic:
        # With an empty environment, we would generally get the true underlying system default
        # encoding, which is unlikely to be what we want (it's generally ASCII, still). So we
        # explicitly set an encoding here.
        env = {"LC_ALL": "en_US.UTF-8"}
        # Apply our allowlist.
        for h in (
            "HOME",
            "PATH",  # Needed to find Python interpreters and other binaries.
            "PANTS_PROFILE",
            "RUN_PANTS_FROM_PEX",
        ):
            value = os.getenv(h)
            if value is not None:
                env[h] = value
        hermetic_env = os.getenv("HERMETIC_ENV")
        if hermetic_env:
            for h in hermetic_env.strip(",").split(","):
                value = os.getenv(h)
                if value is not None:
                    env[h] = value
    else:
        env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    env.update(PYTHONPATH=os.pathsep.join(sys.path))

    # Pants command that was called from the test shouldn't have a parent.
    if "PANTS_PARENT_BUILD_ID" in env:
        del env["PANTS_PARENT_BUILD_ID"]

    return PantsJoinHandle(
        command=pants_command,
        process=subprocess.Popen(
            pants_command,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        ),
        workdir=workdir,
    )


def run_pants_with_workdir(
    command: Command,
    *,
    workdir: str,
    hermetic: bool = True,
    use_pantsd: bool = True,
    config: Mapping | None = None,
    stdin_data: bytes | str | None = None,
    tee_output: bool = False,
    **kwargs: Any,
) -> PantsResult:
    if config:
        kwargs["config"] = config
    handle = run_pants_with_workdir_without_waiting(
        command, workdir=workdir, hermetic=hermetic, use_pantsd=use_pantsd, **kwargs
    )
    return handle.join(stdin_data=stdin_data, tee_output=tee_output)


def run_pants(
    command: Command,
    *,
    hermetic: bool = True,
    use_pantsd: bool = True,
    config: Mapping | None = None,
    extra_env: Mapping[str, str] | None = None,
    stdin_data: bytes | str | None = None,
    **kwargs: Any,
) -> PantsResult:
    """Runs Pants in a subprocess.

    :param command: A list of command line arguments coming after `./pants`.
    :param hermetic: If hermetic, your actual `pants.toml` will not be used.
    :param use_pantsd: If True, the Pants process will use pantsd.
    :param config: Optional data for a generated TOML file. A map of <section-name> ->
        map of key -> value.
    :param extra_env: Set these env vars in the Pants process's environment.
    :param stdin_data: Make this data available to be read from the process's stdin.
    :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
    """
    with temporary_workdir() as workdir:
        return run_pants_with_workdir(
            command,
            workdir=workdir,
            hermetic=hermetic,
            use_pantsd=use_pantsd,
            config=config,
            stdin_data=stdin_data,
            extra_env=extra_env,
            **kwargs,
        )


# -----------------------------------------------------------------------------------------------
# Environment setup.
# -----------------------------------------------------------------------------------------------


@contextmanager
def setup_tmpdir(files: Mapping[str, str]) -> Iterator[str]:
    """Create a temporary directory with the given files and return the tmpdir (relative to the
    build root).

    The `files` parameter is a dictionary of file paths to content. All file paths will be prefixed
    with the tmpdir. The file content can use `{tmpdir}` to have it substituted with the actual
    tmpdir via a format string.

    This is useful to set up controlled test environments, such as setting up source files and
    BUILD files.
    """
    with temporary_dir(root_dir=get_buildroot()) as tmpdir:
        rel_tmpdir = os.path.relpath(tmpdir, get_buildroot())
        for path, content in files.items():
            safe_file_dump(
                os.path.join(tmpdir, path), content.format(tmpdir=rel_tmpdir), makedirs=True
            )
        yield rel_tmpdir


@contextmanager
def temporary_workdir(cleanup: bool = True) -> Iterator[str]:
    # We can hard-code '.pants.d' here because we know that will always be its value
    # in the pantsbuild/pants repo (e.g., that's what we .gitignore in that repo).
    # Grabbing the pants_workdir config would require this pants's config object,
    # which we don't have a reference to here.
    root = os.path.join(get_buildroot(), ".pants.d", "tmp")
    safe_mkdir(root)
    with temporary_dir(root_dir=root, cleanup=cleanup, suffix=".pants.d") as tmpdir:
        yield tmpdir


# -----------------------------------------------------------------------------------------------
# Pantsd and logs.
# -----------------------------------------------------------------------------------------------


def kill_daemon(pid_dir=None):
    args = ["./pants"]
    if pid_dir:
        args.append(f"--pants-subprocessdir={pid_dir}")
    pantsd_client = PantsDaemonClient(
        OptionsBootstrapper.create(env=os.environ, args=args, allow_pantsrc=False).bootstrap_options
    )
    with pantsd_client.lifecycle_lock:
        pantsd_client.terminate()


def ensure_daemon(func):
    """A decorator to assist with running tests with and without the daemon enabled."""
    return pytest.mark.parametrize("use_pantsd", [True, False])(func)


def render_logs(workdir: str) -> None:
    """Renders all potentially relevant logs from the given workdir to stdout."""
    filenames = list(glob.glob(os.path.join(workdir, "logs/exceptions*log"))) + list(
        glob.glob(os.path.join(workdir, "pants.log"))
    )
    for filename in filenames:
        rel_filename = fast_relpath(filename, workdir)
        print(f"{rel_filename} +++ ")
        for line in _read_log(filename):
            print(f"{rel_filename} >>> {line}")
        print(f"{rel_filename} --- ")


def read_pants_log(workdir: str) -> Iterator[str]:
    """Yields all lines from the pants log under the given workdir."""
    # Surface the pants log for easy viewing via pytest's `-s` (don't capture stdio) option.
    yield from _read_log(f"{workdir}/pants.log")


def _read_log(filename: str) -> Iterator[str]:
    with open(filename) as f:
        for line in f:
            yield line.rstrip()
