# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import re
import shutil
import subprocess
import sys
import unittest
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from operator import eq, ne
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterator, List, Optional, Union

from colors import strip_color

from pants.base.build_environment import get_buildroot
from pants.base.build_file import _is_build_file_name
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.fs.archive import ZIP
from pants.option.config import TomlSerializer
from pants.subsystem.subsystem import Subsystem
from pants.testutil.file_test_util import check_symlinks, contains_exact_files
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import fast_relpath, safe_mkdir, safe_mkdir_for, safe_open
from pants.util.osutil import Pid
from pants.util.process_handler import SubprocessProcessHandler
from pants.util.strutil import ensure_binary

# NB: If `shell=True`, it's a single `str`.
Command = Union[str, List[str]]


@dataclass(frozen=True)
class PantsResult:
    command: Command
    returncode: int
    stdout_data: str
    stderr_data: str
    workdir: str
    pid: Pid


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
        (stdout_data, stderr_data) = communicate_fn(stdin_data)

        if self.process.returncode != PANTS_SUCCEEDED_EXIT_CODE:
            render_logs(self.workdir)

        return PantsResult(
            command=self.command,
            returncode=self.process.returncode,
            stdout_data=stdout_data.decode(),
            stderr_data=stderr_data.decode(),
            workdir=self.workdir,
            pid=self.process.pid,
        )


def ensure_cached(expected_num_artifacts=None):
    """Decorator for asserting cache writes in an integration test.

    :param expected_num_artifacts: Expected number of artifacts to be in the task's
                                   cache after running the test. If unspecified, will
                                   assert that the number of artifacts in the cache is
                                   non-zero.
    """

    def decorator(test_fn):
        def wrapper(self, *args, **kwargs):
            with temporary_dir() as artifact_cache:
                cache_args = f'--cache-write-to=["{artifact_cache}"]'

                test_fn(self, *args + (cache_args,), **kwargs)

                num_artifacts = 0
                for (root, _, files) in os.walk(artifact_cache):
                    print(root, files)
                    num_artifacts += len(files)

                if expected_num_artifacts is None:
                    self.assertNotEqual(num_artifacts, 0)
                else:
                    self.assertEqual(num_artifacts, expected_num_artifacts)

        return wrapper

    return decorator


def ensure_daemon(f):
    """A decorator for running an integration test with and without the daemon enabled."""

    def wrapper(self, *args, **kwargs):
        for enable_daemon in [False, True]:
            enable_daemon_str = str(enable_daemon)
            env = {
                "HERMETIC_ENV": "PANTS_ENABLE_PANTSD,PANTS_ENABLE_V2_ENGINE,PANTS_SUBPROCESSDIR",
                "PANTS_ENABLE_PANTSD": enable_daemon_str,
            }
            with environment_as(**env):
                try:
                    f(self, *args, **kwargs)
                    if enable_daemon:
                        self.assert_success(self.run_pants(["kill-pantsd"]))
                except Exception:
                    print(f"Test failed with enable-pantsd={enable_daemon}:")
                    if enable_daemon:
                        # If we are already raising, do not attempt to confirm that `kill-pantsd` succeeds.
                        self.run_pants(["kill-pantsd"])
                    else:
                        print(
                            "Skipping run with enable-pantsd=true because it already failed with enable-pantsd=false."
                        )
                    raise

    return wrapper


def render_logs(workdir):
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


def read_pantsd_log(workdir):
    """Yields all lines from the pantsd log under the given workdir."""
    # Surface the pantsd log for easy viewing via pytest's `-s` (don't capture stdio) option.
    for line in _read_log(f"{workdir}/pantsd/pantsd.log"):
        yield line


def _read_log(filename):
    with open(filename, "r") as f:
        for line in f:
            yield line.rstrip()


class PantsRunIntegrationTest(unittest.TestCase):
    """A base class useful for integration tests for targets in the same repo."""

    class InvalidTestEnvironmentError(Exception):
        """Raised when the external environment is not set up properly to run integration tests."""

    @classmethod
    def use_pantsd_env_var(cls):
        """Subclasses may override to acknowledge that the tests cannot run when pantsd is enabled,
        or they want to configure pantsd themselves.

        In those cases, --enable-pantsd will not be added to their configuration.
        This approach is coarsely grained, meaning we disable pantsd in some tests that actually run
        when pantsd is enabled. However:
          - The number of mislabeled tests is currently small (~20 tests).
          - Those tests will still run, just with pantsd disabled.

        N.B. Currently, this doesn't interact with test hermeticity.
        This means that, if the test coordinator has set PANTS_ENABLE_PANTSD, and a test is not marked
        as hermetic, it will run under pantsd regardless of the value of this function.
        """
        should_pantsd = os.getenv("USE_PANTSD_FOR_INTEGRATION_TESTS")
        return should_pantsd in ["True", "true", "1"]

    @classmethod
    def hermetic(cls):
        """Subclasses may override to acknowledge that they are hermetic.

        That is, that they should run without reading the real pants.toml.
        """
        return False

    @classmethod
    def hermetic_env_whitelist(cls):
        """A whitelist of environment variables to propagate to tests when hermetic=True."""
        return [
            # Used in the wrapper script to locate a rust install.
            "HOME",
            # Needed to find python interpreters and other binaries.
            "PATH",
            "PANTS_PROFILE",
            # Ensure that the underlying ./pants invocation doesn't run from sources
            # (and therefore bootstrap) if we don't want it to.
            "RUN_PANTS_FROM_PEX",
        ]

    def setUp(self):
        super().setUp()
        # Some integration tests rely on clean subsystem state (e.g., to set up a DistributionLocator).
        Subsystem.reset()

    def temporary_workdir(self, cleanup=True):
        # We can hard-code '.pants.d' here because we know that will always be its value
        # in the pantsbuild/pants repo (e.g., that's what we .gitignore in that repo).
        # Grabbing the pants_workdir config would require this pants's config object,
        # which we don't have a reference to here.
        root = os.path.join(get_buildroot(), ".pants.d", "tmp")
        safe_mkdir(root)
        return temporary_dir(root_dir=root, cleanup=cleanup, suffix=".pants.d")

    def temporary_cachedir(self):
        return temporary_dir(suffix="__CACHEDIR")

    def temporary_sourcedir(self):
        return temporary_dir(root_dir=get_buildroot())

    @contextmanager
    def source_clone(self, source_dir):
        with self.temporary_sourcedir() as clone_dir:
            target_spec_dir = os.path.relpath(clone_dir)

            for dir_path, dir_names, file_names in os.walk(source_dir):
                clone_dir_path = os.path.join(clone_dir, os.path.relpath(dir_path, source_dir))
                for dir_name in dir_names:
                    os.mkdir(os.path.join(clone_dir_path, dir_name))
                for file_name in file_names:
                    with open(os.path.join(dir_path, file_name), "r") as f:
                        content = f.read()
                    if _is_build_file_name(file_name):
                        content = content.replace(source_dir, target_spec_dir)
                    with open(os.path.join(clone_dir_path, file_name), "w") as f:
                        f.write(content)

            yield clone_dir

    # Incremented each time we spawn a pants subprocess.
    # Appended to PANTS_PROFILE in the called pants process, so that each subprocess
    # writes to its own profile file, instead of all stomping on the parent process's profile.
    _profile_disambiguator = 0
    _profile_disambiguator_lock = Lock()

    @classmethod
    def _get_profile_disambiguator(cls):
        with cls._profile_disambiguator_lock:
            ret = cls._profile_disambiguator
            cls._profile_disambiguator += 1
            return ret

    def get_cache_subdir(self, cache_dir, subdir_glob="*/", other_dirs=()):
        """Check that there is only one entry of `cache_dir` which matches the glob specified by
        `subdir_glob`, excluding `other_dirs`, and return it.

        :param str cache_dir: absolute path to some directory.
        :param str subdir_glob: string specifying a glob for (one level down)
                                subdirectories of `cache_dir`.
        :param list other_dirs: absolute paths to subdirectories of `cache_dir`
                                which must exist and match `subdir_glob`.
        :return: Assert that there is a single remaining directory entry matching
                 `subdir_glob` after removing `other_dirs`, and return it.

                 This method oes not check if its arguments or return values are
                 files or directories. If `subdir_glob` has a trailing slash, so
                 will the return value of this method.
        """
        subdirs = set(glob.glob(os.path.join(cache_dir, subdir_glob)))
        other_dirs = set(other_dirs)
        self.assertTrue(other_dirs.issubset(subdirs))
        remaining_dirs = subdirs - other_dirs
        self.assertEqual(len(remaining_dirs), 1)
        return list(remaining_dirs)[0]

    def run_pants_with_workdir_without_waiting(
        self,
        command,
        workdir,
        config=None,
        extra_env=None,
        build_root=None,
        print_exception_stacktrace=True,
        **kwargs,
    ) -> PantsJoinHandle:
        args = [
            "--no-pantsrc",
            f"--pants-workdir={workdir}",
            f"--print-exception-stacktrace={print_exception_stacktrace}",
        ]
        # TODO: If the default value for `--v1` changes to False then this check will
        # Have to change to `if '--v1' in command:`.
        if "--no-v1" not in command:
            args.append("--kill-nailguns")

        if self.hermetic():
            args.extend(
                [
                    "--pants-config-files=[]",
                    # Turn off cache globally.  A hermetic integration test shouldn't rely on cache,
                    # or we have no idea if it's actually testing anything.
                    "--no-cache-read",
                    "--no-cache-write",
                    # Turn cache on just for tool bootstrapping, for performance.
                    "--cache-bootstrap-read",
                    "--cache-bootstrap-write",
                ]
            )

        if self.use_pantsd_env_var():
            args.append("--enable-pantsd=True")
            args.append("--no-shutdown-pantsd-after-run")

        if config:
            toml_file_name = os.path.join(workdir, "pants.toml")
            with safe_open(toml_file_name, mode="w") as fp:
                fp.write(TomlSerializer(config).serialize())
            args.append("--pants-config-files=" + toml_file_name)

        pants_script = [sys.executable, "-m", "pants"]

        # Permit usage of shell=True and string-based commands to allow e.g. `./pants | head`.
        if kwargs.get("shell") is True:
            assert not isinstance(
                command, list
            ), "must pass command as a string when using shell=True"
            pants_command = " ".join([*pants_script, " ".join(args), command])
        else:
            pants_command = pants_script + args + command

        # Only whitelisted entries will be included in the environment if hermetic=True.
        if self.hermetic():
            env = dict()
            # With an empty environment, we would generally get the true underlying system default
            # encoding, which is unlikely to be what we want (it's generally ASCII, still). So we
            # explicitly set an encoding here.
            env["LC_ALL"] = "en_US.UTF-8"
            for h in self.hermetic_env_whitelist():
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
            # Make a note the subprocess command, so the user can correctly interpret the profile files.
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
        self, command, workdir, config=None, stdin_data=None, tee_output=False, **kwargs
    ) -> PantsResult:
        if config:
            kwargs["config"] = config
        handle = self.run_pants_with_workdir_without_waiting(command, workdir, **kwargs)
        return handle.join(stdin_data=stdin_data, tee_output=tee_output)

    def run_pants(
        self, command, config=None, stdin_data=None, extra_env=None, cleanup_workdir=True, **kwargs
    ) -> PantsResult:
        """Runs pants in a subprocess.

        :param list command: A list of command line arguments coming after `./pants`.
        :param config: Optional data for a generated TOML file. A map of <section-name> ->
        map of key -> value.
        :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
        """
        with self.temporary_workdir() as workdir:
            return self.run_pants_with_workdir(
                command, workdir, config, stdin_data=stdin_data, extra_env=extra_env, **kwargs
            )

    @contextmanager
    def pants_results(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
        """Similar to run_pants in that it runs pants in a subprocess, but yields in order to give
        callers a chance to do any necessary validations on the workdir.

        :param list command: A list of command line arguments coming after `./pants`.
        :param config: Optional data for a generated TOML file. A map of <section-name> ->
        map of key -> value.
        :param kwargs: Extra keyword args to pass to `subprocess.Popen`.
        :returns a PantsResult instance.
        """
        with self.temporary_workdir() as workdir:
            yield self.run_pants_with_workdir(
                command, workdir, config, stdin_data=stdin_data, extra_env=extra_env, **kwargs
            )

    def bundle_and_run(
        self,
        target,
        bundle_name,
        bundle_jar_name=None,
        bundle_options=None,
        args=None,
        expected_bundle_jar_content=None,
        expected_bundle_content=None,
        library_jars_are_symlinks=True,
    ):
        """Creates the bundle with pants, then does java -jar {bundle_name}.jar to execute the
        bundle.

        :param target: target name to compile
        :param bundle_name: resulting bundle filename (minus .zip extension)
        :param bundle_jar_name: monolithic jar filename (minus .jar extension), if None will be the
          same as bundle_name
        :param bundle_options: additional options for bundle
        :param args: optional arguments to pass to executable
        :param expected_bundle_content: verify the bundle zip content
        :param expected_bundle_jar_content: verify the bundle jar content
        :param library_jars_are_symlinks: verify library jars are symlinks if True, and actual
          files if False. Default `True` because we always create symlinks for both external and internal
          dependencies, only exception is when shading is used.
        :return: stdout as a string on success, raises an Exception on error
        """
        bundle_jar_name = bundle_jar_name or bundle_name
        bundle_options = bundle_options or []
        bundle_options = ["bundle.jvm"] + bundle_options + ["--archive=zip", target]
        with self.pants_results(bundle_options) as pants_run:
            self.assert_success(pants_run)

            self.assertTrue(
                check_symlinks(f"dist/{bundle_name}-bundle/libs", library_jars_are_symlinks)
            )
            # TODO(John Sirois): We need a zip here to suck in external library classpath elements
            # pointed to by symlinks in the run_pants ephemeral tmpdir.  Switch run_pants to be a
            # contextmanager that yields its results while the tmpdir workdir is still active and change
            # this test back to using an un-archived bundle.
            with temporary_dir() as workdir:
                ZIP.extract(f"dist/{bundle_name}.zip", workdir)
                if expected_bundle_content:
                    self.assertTrue(contains_exact_files(workdir, expected_bundle_content))
                if expected_bundle_jar_content:
                    with temporary_dir() as check_bundle_jar_dir:
                        bundle_jar = os.path.join(workdir, f"{bundle_jar_name}.jar")
                        ZIP.extract(bundle_jar, check_bundle_jar_dir)
                        self.assertTrue(
                            contains_exact_files(check_bundle_jar_dir, expected_bundle_jar_content)
                        )

                optional_args = []
                if args:
                    optional_args = args
                java_run = subprocess.Popen(
                    ["java", "-jar", f"{bundle_jar_name}.jar"] + optional_args,
                    stdout=subprocess.PIPE,
                    cwd=workdir,
                )

                stdout, _ = java_run.communicate()
            java_returncode = java_run.returncode
            self.assertEqual(java_returncode, 0)
            return stdout.decode()

    def assert_success(self, pants_run: PantsResult, msg=None):
        self.assert_result(pants_run, PANTS_SUCCEEDED_EXIT_CODE, expected=True, msg=msg)

    def assert_failure(self, pants_run: PantsResult, msg=None):
        self.assert_result(pants_run, PANTS_SUCCEEDED_EXIT_CODE, expected=False, msg=msg)

    def assert_result(self, pants_run: PantsResult, value, expected=True, msg=None):
        check, assertion = (eq, self.assertEqual) if expected else (ne, self.assertNotEqual)
        if check(pants_run.returncode, value):
            return

        details = [msg] if msg else []
        details.append(" ".join(pants_run.command))
        details.append(f"returncode: {pants_run.returncode}")

        def indent(content):
            return "\n\t".join(content.splitlines())

        details.append(f"stdout:\n\t{indent(pants_run.stdout_data)}")
        details.append(f"stderr:\n\t{indent(pants_run.stderr_data)}")
        error_msg = "\n".join(details)

        assertion(value, pants_run.returncode, error_msg)

    def assert_run_contains_log(self, msg, level, module, pants_run: PantsResult):
        """Asserts that the passed run's stderr contained the log message."""
        self.assert_contains_log(msg, level, module, pants_run.stderr_data, pants_run.pid)

    def assert_contains_log(self, msg, level, module, log, pid=None):
        """Asserts that the passed log contains the message logged by the module at the level.

        If pid is specified, performs an exact match including the pid of the pants process.
        Otherwise performs a regex match asserting that some pid is present.
        """
        prefix = f"[{level}] {module}:pid="
        suffix = f": {msg}"
        if pid is None:
            self.assertRegex(log, re.escape(prefix) + r"\d+" + re.escape(suffix))
        else:
            self.assertIn(f"{prefix}{pid}{suffix}", log)

    def assert_is_file(self, file_path):
        self.assertTrue(os.path.isfile(file_path), f"file path {file_path} does not exist!")

    def assert_is_not_file(self, file_path):
        self.assertFalse(os.path.isfile(file_path), f"file path {file_path} exists!")

    def normalize(self, s: str) -> str:
        """Removes escape sequences (e.g. colored output) and all whitespace from string s."""
        return "".join(strip_color(s).split())

    @contextmanager
    def file_renamed(self, prefix, test_name, real_name):
        real_path = os.path.join(prefix, real_name)
        test_path = os.path.join(prefix, test_name)
        try:
            os.rename(test_path, real_path)
            yield
        finally:
            os.rename(real_path, test_path)

    @contextmanager
    def temporary_directory_literal(self, path: Union[str, Path],) -> Iterator[None]:
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
        self, path: Union[str, Path], content, binary_mode=True
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

    @contextmanager
    def mock_buildroot(self, dirs_to_copy=None):
        """Construct a mock buildroot and return a helper object for interacting with it."""

        @dataclass(frozen=True)
        class Manager:
            write_file: Callable[[str, str], None]
            pushd: Any
            new_buildroot: str

        # N.B. BUILD.tools, contrib, 3rdparty needs to be copied vs symlinked to avoid
        # symlink prefix check error in v1 and v2 engine.
        files_to_copy = ("BUILD.tools",)
        files_to_link = (
            "BUILD_ROOT",
            ".isort.cfg",
            ".pants.d",
            "build-support",
            # NB: when running with --chroot or the V2 engine, `pants` refers to the source root-stripped
            # directory src/python/pants, not the script `./pants`.
            "pants",
            "pants.pex",
            "pants-plugins",
            "pants.toml",
            "pants.travis-ci.toml",
            "pyproject.toml",
            "rust-toolchain",
            "src",
        )
        dirs_to_copy = ("3rdparty", *(dirs_to_copy or []))

        with self.temporary_workdir() as tmp_dir:
            for filename in files_to_copy:
                shutil.copy(
                    os.path.join(get_buildroot(), filename), os.path.join(tmp_dir, filename)
                )

            for dirname in dirs_to_copy:
                shutil.copytree(
                    os.path.join(get_buildroot(), dirname), os.path.join(tmp_dir, dirname)
                )

            for filename in files_to_link:
                link_target = os.path.join(get_buildroot(), filename)
                if os.path.exists(link_target):
                    os.symlink(link_target, os.path.join(tmp_dir, filename))

            def write_file(file_path, contents):
                full_file_path = os.path.join(tmp_dir, *file_path.split(os.pathsep))
                safe_mkdir_for(full_file_path)
                with open(full_file_path, "w") as fh:
                    fh.write(contents)

            @contextmanager
            def dir_context():
                with pushd(tmp_dir):
                    yield

            yield Manager(write_file, dir_context, tmp_dir)

    def do_command(self, *args, **kwargs) -> PantsResult:
        """Wrapper around run_pants method.

        :param args: command line arguments used to run pants
        """
        cmd = list(args)
        success = kwargs.pop("success", True)
        pants_run = self.run_pants(cmd, **kwargs)
        if success:
            self.assert_success(pants_run)
        else:
            self.assert_failure(pants_run)
        return pants_run

    @contextmanager
    def do_command_yielding_workdir(self, *args, **kwargs):
        cmd = list(args)
        success = kwargs.pop("success", True)
        with self.pants_results(cmd, **kwargs) as pants_run:
            if success:
                self.assert_success(pants_run)
            else:
                self.assert_failure(pants_run)
            yield pants_run
