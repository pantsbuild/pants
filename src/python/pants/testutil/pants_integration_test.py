# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import glob
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Mapping, Union

import pytest

from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.option.config import TomlSerializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_file_dump, safe_mkdir
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
    workdir: str | None

    def join(self, stdin_data: bytes | str | None = None) -> PantsResult:
        """Wait for the pants process to complete, and return a PantsResult for it."""
        if stdin_data is not None:
            stdin_data = ensure_binary(stdin_data)
        (stdout, stderr) = self.process.communicate(stdin_data)

        if self.process.returncode != PANTS_SUCCEEDED_EXIT_CODE:
            render_logs(self.workdir or ".pants.d")

        return PantsResult(
            command=self.command,
            exit_code=self.process.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            pid=self.process.pid,
        )


def run_pants_without_waiting(
    command: Command,
    *,
    workdir: str | None,
    hermetic: bool = True,
    use_pantsd: bool = True,
    config: Mapping | None = None,
    extra_env: Mapping[str, str] | None = None,
    shell: bool = False,
) -> PantsJoinHandle:
    args = ["--no-pantsrc"]
    if workdir:
        args.append(f"--pants-workdir={workdir}")

    pantsd_in_command = "--no-pantsd" in command or "--pantsd" in command
    pantsd_in_config = config and "GLOBAL" in config and "pantsd" in config["GLOBAL"]
    if not pantsd_in_command and not pantsd_in_config:
        args.append("--pantsd" if use_pantsd else "--no-pantsd")

    if hermetic:
        args.append("--pants-config-files=[]")
        # Certain tests may be invoking `./pants test` for a pytest test with conftest discovery
        # enabled. We should ignore the root conftest.py for these cases.
        args.append("--pants-ignore=/conftest.py")

    if config:
        toml_file_name = "pants.test_config.toml"
        with Path(toml_file_name).open("w") as fp:
            fp.write(TomlSerializer(config).serialize())
        args.append(f"--pants-config-files={toml_file_name}")

    pants_script = [sys.executable, "-m", "pants"]

    # Permit usage of shell=True and string-based commands to allow e.g. `./pants | head`.
    pants_command: Command
    if shell:
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
            shell=shell,
        ),
        workdir=workdir,
    )


def run_pants(
    command: Command,
    *,
    workdir: str | None = None,
    hermetic: bool = True,
    use_pantsd: bool = True,
    config: Mapping | None = None,
    extra_env: Mapping[str, str] | None = None,
    stdin_data: bytes | str | None = None,
    shell: bool = False,
) -> PantsResult:
    """Runs Pants in a subprocess.

    :param command: A list of command line arguments coming after `./pants`.
    :param workdir: Where to write Pantsd logs, with default to `.pants.d`.
    :param hermetic: If hermetic, your actual `pants.toml` will not be used.
    :param use_pantsd: If True, the Pants process will use pantsd.
    :param config: Optional data for a generated TOML file. A map of <section-name> ->
        map of key -> value.
    :param extra_env: Set these env vars in the Pants process's environment.
    :param stdin_data: Make this data available to be read from the process's stdin.
    :param shell: if true, run with `subprocess.Popen(shell=True)`.
    """
    handle = run_pants_without_waiting(
        command,
        workdir=workdir,
        hermetic=hermetic,
        use_pantsd=use_pantsd,
        shell=shell,
        config=config,
        extra_env=extra_env,
    )
    return handle.join(stdin_data=stdin_data)


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
