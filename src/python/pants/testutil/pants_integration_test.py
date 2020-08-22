# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import subprocess
import sys
import unittest
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterator, List, Mapping, Optional, Union

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import warn_or_error
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.option.config import TomlSerializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient
from pants.testutil.process_handler import SubprocessProcessHandler
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import fast_relpath, safe_mkdir, safe_open
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

    @property
    def returncode(self) -> int:
        warn_or_error(
            removal_version="2.1.0.dev0",
            deprecated_entity_description="the property PantsResult.returncode",
            hint="Use `PantsResult.exit_code` instead.",
        )
        return self.exit_code

    @property
    def stdout_data(self) -> str:
        warn_or_error(
            removal_version="2.1.0.dev0",
            deprecated_entity_description="the property PantsResult.stdout_data",
            hint="Use `PantsResult.stdout` instead.",
        )
        return self.stdout

    @property
    def stderr_data(self) -> str:
        warn_or_error(
            removal_version="2.1.0.dev0",
            deprecated_entity_description="the property PantsResult.stderr_data",
            hint="Use `PantsResult.stderr` instead.",
        )
        return self.stderr


@dataclass(frozen=True)
class PantsJoinHandle:
    command: Command
    process: subprocess.Popen
    workdir: str

    def join(
        self, stdin_data: Optional[Union[bytes, str]] = None, tee_output: bool = False
    ) -> PantsResult:
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


def kill_daemon(pid_dir=None):
    args = ["./pants"]
    if pid_dir:
        args.append(f"--pants-subprocessdir={pid_dir}")
    pantsd_client = PantsDaemonClient(
        OptionsBootstrapper.create(env=os.environ, args=args, allow_pantsrc=False).bootstrap_options
    )
    with pantsd_client.lifecycle_lock:
        pantsd_client.terminate()


def ensure_daemon(f):
    """A decorator for running an integration test with and without the daemon enabled."""

    def wrapper(self, *args, **kwargs):
        for enable_daemon in [False, True]:
            enable_daemon_str = str(enable_daemon)
            env = {
                "HERMETIC_ENV": "PANTS_PANTSD,PANTS_SUBPROCESSDIR",
                "PANTS_PANTSD": enable_daemon_str,
            }
            with environment_as(**env):
                try:
                    f(self, *args, **kwargs)
                except Exception:
                    print(f"Test failed with enable-pantsd={enable_daemon}:")
                    if not enable_daemon:
                        print(
                            "Skipping run with pantsd=true because it already "
                            "failed with pantsd=false."
                        )
                    raise
                finally:
                    kill_daemon()

    return wrapper


def render_logs(workdir: str) -> None:
    """Renders all potentially relevant logs from the given workdir to stdout."""
    filenames = list(glob.glob(os.path.join(workdir, "logs/exceptions*log"))) + list(
        glob.glob(os.path.join(workdir, "pantsd/pantsd.log"))
    )
    for filename in filenames:
        rel_filename = fast_relpath(filename, workdir)
        print(f"{rel_filename} +++ ")
        for line in _read_log(filename):
            print(f"{rel_filename} >>> {line}")
        print(f"{rel_filename} --- ")


def read_pantsd_log(workdir: str) -> Iterator[str]:
    """Yields all lines from the pantsd log under the given workdir."""
    # Surface the pantsd log for easy viewing via pytest's `-s` (don't capture stdio) option.
    for line in _read_log(f"{workdir}/pantsd/pantsd.log"):
        yield line


def _read_log(filename: str) -> Iterator[str]:
    with open(filename, "r") as f:
        for line in f:
            yield line.rstrip()


class PantsIntegrationTest(unittest.TestCase):
    """A base class for integration tests that run Pants."""

    # Classes can optionally override these.
    hermetic = True  # If False, pants.toml will be used.
    hermetic_env_allowlist = (
        "HOME",
        "PATH",  # Needed to find Python interpreters and other binaries.
        "PANTS_PROFILE",
        "RUN_PANTS_FROM_PEX",
    )
    use_pantsd = True

    # Incremented each time we spawn a pants subprocess.
    # Appended to PANTS_PROFILE in the called pants process, so that each subprocess
    # writes to its own profile file, instead of all stomping on the parent process's profile.
    _profile_disambiguator = 0
    _profile_disambiguator_lock = Lock()

    @classmethod
    def _get_profile_disambiguator(cls) -> int:
        with cls._profile_disambiguator_lock:
            ret = cls._profile_disambiguator
            cls._profile_disambiguator += 1
            return ret

    def run_pants_with_workdir_without_waiting(
        self,
        command: Command,
        *,
        workdir: str,
        config: Optional[Mapping] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        print_exception_stacktrace: bool = True,
        **kwargs: Any,
    ) -> PantsJoinHandle:
        args = [
            "--no-pantsrc",
            f"--pants-workdir={workdir}",
            f"--print-exception-stacktrace={print_exception_stacktrace}",
        ]

        if "--no-pantsd" not in args and "--pantsd" not in args:
            args.append("--pantsd" if self.use_pantsd else "--no-pantsd")

        if self.hermetic:
            args.append("--pants-config-files=[]")

        if config:
            toml_file_name = os.path.join(workdir, "pants.toml")
            with safe_open(toml_file_name, mode="w") as fp:
                fp.write(TomlSerializer(config).serialize())  # type: ignore[arg-type]
            args.append(f"--pants-config-files={toml_file_name}")

        pants_script = [sys.executable, "-m", "pants"]

        # Permit usage of shell=True and string-based commands to allow e.g. `./pants | head`.
        pants_command: Command
        if kwargs.get("shell") is True:
            assert not isinstance(
                command, list
            ), "must pass command as a string when using shell=True"
            pants_command = " ".join([*pants_script, " ".join(args), command])
        else:
            pants_command = [*pants_script, *args, *command]

        # Only allow-listed entries will be included in the environment if hermetic=True. Note that
        # the env will already be fairly hermetic thanks to the v2 engine; this provides an
        # additional layer of hermiticity.
        if self.hermetic:
            # With an empty environment, we would generally get the true underlying system default
            # encoding, which is unlikely to be what we want (it's generally ASCII, still). So we
            # explicitly set an encoding here.
            env = {"LC_ALL": "en_US.UTF-8"}
            for h in self.hermetic_env_allowlist:
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

        # Don't overwrite the profile of this process in the called process.
        # Instead, write the profile into a sibling file.
        if env.get("PANTS_PROFILE"):
            prof = f"{env['PANTS_PROFILE']}.{self._get_profile_disambiguator()}"
            env["PANTS_PROFILE"] = prof
            # Make a note of the subprocess command, so the user can correctly interpret the
            # profile files.
            with open(f"{prof}.cmd", "w") as fp:
                fp.write(" ".join(pants_command))

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
        self,
        command: Command,
        *,
        workdir: str,
        config: Optional[Mapping] = None,
        stdin_data: Optional[Union[bytes, str]] = None,
        tee_output: bool = False,
        **kwargs: Any,
    ) -> PantsResult:
        if config:
            kwargs["config"] = config
        handle = self.run_pants_with_workdir_without_waiting(command, workdir=workdir, **kwargs)
        return handle.join(stdin_data=stdin_data, tee_output=tee_output)

    def run_pants(
        self,
        command: Command,
        config: Optional[Mapping] = None,
        stdin_data: Optional[Union[bytes, str]] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> PantsResult:
        """Runs Pants in a subprocess.

        :param command: A list of command line arguments coming after `./pants`.
        :param config: Optional data for a generated TOML file. A map of <section-name> ->
            map of key -> value.
        :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
        """
        with self.temporary_workdir() as workdir:
            return self.run_pants_with_workdir(
                command,
                workdir=workdir,
                config=config,
                stdin_data=stdin_data,
                extra_env=extra_env,
                **kwargs,
            )

    def assert_success(self, pants_run: PantsResult, msg: Optional[str] = None) -> None:
        self._assert_result(pants_run, success_expected=True, msg=msg)

    def assert_failure(self, pants_run: PantsResult, msg: Optional[str] = None) -> None:
        self._assert_result(pants_run, success_expected=False, msg=msg)

    @staticmethod
    def _assert_result(
        pants_run: PantsResult, *, success_expected: bool, msg: Optional[str]
    ) -> None:
        is_expected_exit_code = (
            pants_run.exit_code == PANTS_SUCCEEDED_EXIT_CODE
            if success_expected
            else pants_run.exit_code != PANTS_SUCCEEDED_EXIT_CODE
        )
        if is_expected_exit_code:
            return

        details = [msg] if msg else []
        details.append(" ".join(pants_run.command))
        details.append(f"exit_code: {pants_run.exit_code}")

        def indent(content):
            return "\n\t".join(content.splitlines())

        details.append(f"stdout:\n\t{indent(pants_run.stdout)}")
        details.append(f"stderr:\n\t{indent(pants_run.stderr)}")
        error_msg = "\n".join(details)

        assert is_expected_exit_code, error_msg

    @staticmethod
    def temporary_workdir(cleanup: bool = True):
        # We can hard-code '.pants.d' here because we know that will always be its value
        # in the pantsbuild/pants repo (e.g., that's what we .gitignore in that repo).
        # Grabbing the pants_workdir config would require this pants's config object,
        # which we don't have a reference to here.
        root = os.path.join(get_buildroot(), ".pants.d", "tmp")
        safe_mkdir(root)
        return temporary_dir(root_dir=root, cleanup=cleanup, suffix=".pants.d")

    @contextmanager
    def temporary_directory_literal(self, path: Union[str, Path]) -> Iterator[None]:
        """Temporarily create the given literal directory under the buildroot.

        The path being created must not already exist. Any parent directories will also be created
        temporarily.
        """
        path = os.path.realpath(path)
        assert path.startswith(
            os.path.realpath(get_buildroot())
        ), "cannot write paths outside of the buildroot!"
        assert not os.path.exists(path), "refusing to overwrite an existing path!"

        parent = os.path.dirname(path)
        parent_ctx = (
            suppress() if os.path.isdir(parent) else self.temporary_directory_literal(parent)
        )

        with parent_ctx:
            try:
                os.mkdir(path)
                yield
            finally:
                os.rmdir(path)

    @contextmanager
    def temporary_file_content(
        self, path: Union[str, Path], content, binary_mode: bool = True
    ) -> Iterator[None]:
        """Temporarily write content to a file for the purpose of an integration test."""
        path = os.path.realpath(path)
        assert path.startswith(
            os.path.realpath(get_buildroot())
        ), "cannot write paths outside of the buildroot!"
        assert not os.path.exists(path), "refusing to overwrite an existing path!"
        mode = "wb" if binary_mode else "w"

        parent = os.path.dirname(path)
        parent_ctx = (
            suppress() if os.path.isdir(parent) else self.temporary_directory_literal(parent)
        )
        with parent_ctx:
            try:
                with open(path, mode) as fh:
                    fh.write(content)
                yield
            finally:
                os.unlink(path)

    @contextmanager
    def with_overwritten_file_content(
        self,
        file_path: Union[str, Path],
        temporary_content: Optional[Union[bytes, str, Callable[[bytes], bytes]]] = None,
    ) -> Iterator[None]:
        """A helper that resets a file after the method runs.

         It will read a file, save the content, maybe write temporary_content to it, yield, then write the
         original content to the file.

        :param file_path: Absolute path to the file to be reset after the method runs.
        :param temporary_content: Content to write to the file, or a function from current content
          to new temporary content.
        """
        with open(file_path, "rb") as f:
            file_original_content = f.read()

        try:
            if temporary_content is not None:
                if callable(temporary_content):
                    content = temporary_content(file_original_content)
                elif isinstance(temporary_content, bytes):
                    content = temporary_content
                else:
                    content = temporary_content.encode()
                with open(file_path, "wb") as f:
                    f.write(content)
            yield

        finally:
            with open(file_path, "wb") as f:
                f.write(file_original_content)
