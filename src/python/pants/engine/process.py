# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
from typing import TYPE_CHECKING, Iterable, Mapping, Tuple

from pants.base.exception_sink import ExceptionSink
from pants.engine.collection import DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, FileDigest
from pants.engine.internals.selectors import MultiGet
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule, side_effecting
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import create_path_env_var, pluralize

if TYPE_CHECKING:
    from pants.engine.internals.scheduler import SchedulerSession


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductDescription:
    value: str


class ProcessCacheScope(Enum):
    # Cached in all locations, regardless of success or failure.
    ALWAYS = "always"
    # Cached in all locations, but only if the process exits successfully.
    SUCCESSFUL = "successful"
    # Cached only in memory (i.e. memoized in pantsd), but never persistently.
    PER_RESTART = "per_restart"
    # Never cached anywhere: will run once per Session (i.e. once per run of Pants).
    NEVER = "never"


@frozen_after_init
@dataclass(unsafe_hash=True)
class Process:
    argv: Tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest
    working_directory: str | None
    env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]
    output_files: Tuple[str, ...]
    output_directories: Tuple[str, ...]
    timeout_seconds: int | float
    jdk_home: str | None
    is_nailgunnable: bool
    execution_slot_variable: str | None
    cache_scope: ProcessCacheScope

    def __init__(
        self,
        argv: Iterable[str],
        *,
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest = EMPTY_DIGEST,
        working_directory: str | None = None,
        env: Mapping[str, str] | None = None,
        append_only_caches: Mapping[str, str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        timeout_seconds: int | float | None = None,
        jdk_home: str | None = None,
        is_nailgunnable: bool = False,
        execution_slot_variable: str | None = None,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> None:
        """Request to run a subprocess, similar to subprocess.Popen.

        This process will be hermetic, meaning that it cannot access files and environment variables
        that are not explicitly populated. For example, $PATH will not be defined by default, unless
        populated through the `env` parameter.

        Usually, you will want to provide input files/directories via the parameter `input_digest`.
        The process will then be able to access these paths through relative paths. If you want to
        give multiple input digests, first merge them with `await Get(Digest, MergeDigests)`.

        Often, you will want to capture the files/directories created in the process. To do this,
        you can either set `output_files` or `output_directories`. The specified paths should be
        specified relative to the `working_directory`, if any, and will then be used to populate
        `output_digest` on the `ProcessResult`. If you want to split up this output digest into
        multiple digests, use `await Get(Digest, DigestSubset)` on the `output_digest`.

        To actually run the process, use `await Get(ProcessResult, Process)` or
        `await Get(FallibleProcessResult, Process)`.

        Example:

            result = await Get(
                ProcessResult, Process(["/bin/echo", "hello world"], description="demo")
            )
            assert result.stdout == b"hello world"
        """
        if isinstance(argv, str):
            raise ValueError("argv must be a sequence of strings, but was a single string.")
        self.argv = tuple(argv)
        self.description = description
        self.level = level
        self.input_digest = input_digest
        self.working_directory = working_directory
        self.env = FrozenDict(env or {})
        self.append_only_caches = FrozenDict(append_only_caches or {})
        self.output_files = tuple(output_files or ())
        self.output_directories = tuple(output_directories or ())
        # NB: A negative or None time value is normalized to -1 to ease the transfer to Rust.
        self.timeout_seconds = timeout_seconds if timeout_seconds and timeout_seconds > 0 else -1
        self.jdk_home = jdk_home
        self.is_nailgunnable = is_nailgunnable
        self.execution_slot_variable = execution_slot_variable
        self.cache_scope = cache_scope


@frozen_after_init
@dataclass(unsafe_hash=True)
class MultiPlatformProcess:
    platform_constraints: tuple[str | None, ...]
    processes: Tuple[Process, ...]

    def __init__(self, request_dict: dict[Platform | None, Process]) -> None:
        if len(request_dict) == 0:
            raise ValueError("At least one platform-constrained Process must be passed.")
        serialized_constraints = tuple(
            constraint.value if constraint else None for constraint in request_dict
        )
        if len([req.description for req in request_dict.values()]) != 1:
            raise ValueError(
                f"The `description` of all processes in a {MultiPlatformProcess.__name__} must "
                f"be identical, but got: {list(request_dict.values())}."
            )

        self.platform_constraints = serialized_constraints
        self.processes = tuple(request_dict.values())

    @property
    def product_description(self) -> ProductDescription:
        return ProductDescription(self.processes[0].description)


@dataclass(frozen=True)
class ProcessResult:
    """Result of executing a process which should not fail.

    If the process has a non-zero exit code, this will raise an exception, unlike
    FallibleProcessResult.
    """

    stdout: bytes
    stdout_digest: FileDigest
    stderr: bytes
    stderr_digest: FileDigest
    output_digest: Digest


@dataclass(frozen=True)
class FallibleProcessResult:
    """Result of executing a process which might fail.

    If the process has a non-zero exit code, this will not raise an exception, unlike ProcessResult.
    """

    stdout: bytes
    stdout_digest: FileDigest
    stderr: bytes
    stderr_digest: FileDigest
    exit_code: int
    output_digest: Digest


@dataclass(frozen=True)
class FallibleProcessResultWithPlatform:
    """Result of executing a process which might fail, along with the platform it ran on."""

    stdout: bytes
    stdout_digest: FileDigest
    stderr: bytes
    stderr_digest: FileDigest
    exit_code: int
    output_digest: Digest
    platform: Platform


class ProcessExecutionFailure(Exception):
    """Used to denote that a process exited, but was unsuccessful in some way.

    For example, exiting with a non-zero code.
    """

    def __init__(
        self, exit_code: int, stdout: bytes, stderr: bytes, process_description: str
    ) -> None:
        # These are intentionally "public" members.
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        # NB: We don't use dedent on a single format string here because it would attempt to
        # interpret the stdio content.
        super().__init__(
            "\n".join(
                [
                    f"Process '{process_description}' failed with exit code {exit_code}.",
                    "stdout:",
                    stdout.decode(),
                    "stderr:",
                    stderr.decode(),
                ]
            )
        )


@rule
def get_multi_platform_request_description(req: MultiPlatformProcess) -> ProductDescription:
    return req.product_description


@rule
def upcast_process(req: Process) -> MultiPlatformProcess:
    """This rule allows an Process to be run as a platform compatible MultiPlatformProcess."""
    return MultiPlatformProcess({None: req})


@rule
def fallible_to_exec_result_or_raise(
    fallible_result: FallibleProcessResult, description: ProductDescription
) -> ProcessResult:
    """Converts a FallibleProcessResult to a ProcessResult or raises an error."""

    if fallible_result.exit_code == 0:
        return ProcessResult(
            stdout=fallible_result.stdout,
            stdout_digest=fallible_result.stdout_digest,
            stderr=fallible_result.stderr,
            stderr_digest=fallible_result.stderr_digest,
            output_digest=fallible_result.output_digest,
        )
    raise ProcessExecutionFailure(
        fallible_result.exit_code,
        fallible_result.stdout,
        fallible_result.stderr,
        description.value,
    )


@rule
def remove_platform_information(res: FallibleProcessResultWithPlatform) -> FallibleProcessResult:
    return FallibleProcessResult(
        exit_code=res.exit_code,
        stdout=res.stdout,
        stdout_digest=res.stdout_digest,
        stderr=res.stderr,
        stderr_digest=res.stderr_digest,
        output_digest=res.output_digest,
    )


@dataclass(frozen=True)
class InteractiveProcessResult:
    exit_code: int


@frozen_after_init
@dataclass(unsafe_hash=True)
class InteractiveProcess:
    argv: Tuple[str, ...]
    env: FrozenDict[str, str]
    input_digest: Digest
    run_in_workspace: bool
    forward_signals_to_process: bool

    def __init__(
        self,
        argv: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        input_digest: Digest = EMPTY_DIGEST,
        run_in_workspace: bool = False,
        forward_signals_to_process: bool = True,
    ) -> None:
        """Request to run a subprocess in the foreground, similar to subprocess.run().

        Unlike `Process`, the result will not be cached.

        To run the process, request `InteractiveRunner` in a `@goal_rule`, then use
        `interactive_runner.run()`.

        `forward_signals_to_process` controls whether pants will allow a SIGINT signal
        sent to a process by hitting Ctrl-C in the terminal to actually reach the process,
        or capture that signal itself, blocking it from the process.
        """
        self.argv = tuple(argv)
        self.env = FrozenDict(env or {})
        self.input_digest = input_digest
        self.run_in_workspace = run_in_workspace
        self.forward_signals_to_process = forward_signals_to_process

        self.__post_init__()

    def __post_init__(self):
        if self.input_digest != EMPTY_DIGEST and self.run_in_workspace:
            raise ValueError(
                "InteractiveProcessRequest should use the Workspace API to materialize any needed "
                "files when it runs in the workspace"
            )

    @classmethod
    def from_process(
        cls,
        process: Process,
        *,
        forward_signals_to_process: bool = True,
    ) -> InteractiveProcess:
        return InteractiveProcess(
            argv=process.argv,
            env=process.env,
            input_digest=process.input_digest,
            forward_signals_to_process=forward_signals_to_process,
        )


@side_effecting
@dataclass(frozen=True)
class InteractiveRunner:
    _scheduler: "SchedulerSession"

    def run(self, request: InteractiveProcess) -> InteractiveProcessResult:
        if request.forward_signals_to_process:
            with ExceptionSink.ignoring_sigint():
                return self._scheduler.run_local_interactive_process(request)

        return self._scheduler.run_local_interactive_process(request)


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryPathTest:
    args: Tuple[str, ...]
    fingerprint_stdout: bool

    def __init__(self, args: Iterable[str], fingerprint_stdout: bool = True) -> None:
        self.args = tuple(args)
        self.fingerprint_stdout = fingerprint_stdout


class SearchPath(DeduplicatedCollection[str]):
    """The search path for binaries; i.e.: the $PATH."""


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryPathRequest:
    """Request to find a binary of a given name.

    If a `test` is specified all binaries that are found will be executed with the test args and
    only those binaries whose test executions exit with return code 0 will be retained.
    Additionally, if test execution includes stdout content, that will be used to fingerprint the
    binary path so that upgrades and downgrades can be detected. A reasonable test for many programs
    might be `BinaryPathTest(args=["--version"])` since it will both ensure the program runs and
    also produce stdout text that changes upon upgrade or downgrade of the binary at the discovered
    path.
    """

    search_path: SearchPath
    binary_name: str
    test: BinaryPathTest | None

    def __init__(
        self,
        *,
        search_path: Iterable[str],
        binary_name: str,
        test: BinaryPathTest | None = None,
    ) -> None:
        self.search_path = SearchPath(search_path)
        self.binary_name = binary_name
        self.test = test


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryPath:
    path: str
    fingerprint: str

    def __init__(self, path: str, fingerprint: str | None = None) -> None:
        self.path = path
        self.fingerprint = self._fingerprint() if fingerprint is None else fingerprint

    @staticmethod
    def _fingerprint(content: bytes | bytearray | memoryview | None = None) -> str:
        hasher = hashlib.sha256() if content is None else hashlib.sha256(content)
        return hasher.hexdigest()

    @classmethod
    def fingerprinted(
        cls, path: str, representative_content: bytes | bytearray | memoryview
    ) -> BinaryPath:
        return cls(path, fingerprint=cls._fingerprint(representative_content))


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryPaths(EngineAwareReturnType):
    binary_name: str
    paths: Tuple[BinaryPath, ...]

    def __init__(self, binary_name: str, paths: Iterable[BinaryPath] | None = None):
        self.binary_name = binary_name
        self.paths = tuple(OrderedSet(paths) if paths else ())

    def message(self) -> str:
        if not self.paths:
            return f"failed to find {self.binary_name}"
        found_msg = f"found {self.binary_name} at {self.paths[0]}"
        if len(self.paths) > 1:
            found_msg = f"{found_msg} and {pluralize(len(self.paths) - 1, 'other location')}"
        return found_msg

    @property
    def first_path(self) -> BinaryPath | None:
        """Return the first path to the binary that was discovered, if any."""
        return next(iter(self.paths), None)


class BinaryNotFoundError(EnvironmentError):
    def __init__(
        self,
        request: BinaryPathRequest,
        *,
        rationale: str | None = None,
        alternative_solution: str | None = None,
    ) -> None:
        """When no binary is found via `BinaryPaths`, and it is not recoverable.

        :param rationale: A short description of why this binary is needed, e.g.
            "download the tools Pants needs" or "run Python programs".
        :param alternative_solution: A description of what else users can do to fix the issue,
            beyond installing the program. For example, "Alternatively, you can set the option
            `--python-setup-interpreter-search-path` to change the paths searched."
        """
        msg = (
            f"Cannot find `{request.binary_name}` on `{sorted(request.search_path)}`. Please "
            "ensure that it is installed"
        )
        msg += f" so that Pants can {rationale}." if rationale else "."
        if alternative_solution:
            msg += f"\n\n{alternative_solution}"
        super().__init__(msg)


class BashBinary(BinaryPath):
    """The `bash` binary."""

    DEFAULT_SEARCH_PATH = SearchPath(("/usr/bin", "/bin", "/usr/local/bin"))


@dataclass(frozen=True)
class BashBinaryRequest:
    rationale: str
    search_path: SearchPath = BashBinary.DEFAULT_SEARCH_PATH


@rule(desc="Finding the `bash` binary", level=LogLevel.DEBUG)
async def find_bash(bash_request: BashBinaryRequest) -> BashBinary:
    request = BinaryPathRequest(
        binary_name="bash",
        search_path=bash_request.search_path,
        test=BinaryPathTest(args=["--version"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError(request, rationale=bash_request.rationale)
    return BashBinary(first_path.path, first_path.fingerprint)


@rule
async def get_bash() -> BashBinary:
    # Expose bash to external consumers.
    return await Get(BashBinary, BashBinaryRequest(rationale="execute bash scripts"))


@rule
async def find_binary(request: BinaryPathRequest) -> BinaryPaths:
    # If we are not already locating bash, recurse to locate bash to use it as an absolute path in
    # our shebang. This avoids mixing locations that we would search for bash into the search paths
    # of the request we are servicing.
    # TODO(#10769): Replace this script with a statically linked native binary so we don't
    #  depend on either /bin/bash being available on the Process host.
    if request.binary_name == "bash":
        shebang = "#!/usr/bin/env bash"
    else:
        bash = await Get(
            BashBinary, BashBinaryRequest(rationale="use it to locate other executables")
        )
        shebang = f"#!{bash.path}"

    # Note: the backslash after the """ marker ensures that the shebang is at the start of the
    # script file. Many OSs will not see the shebang if there is intervening whitespace.
    script_path = "./find_binary.sh"
    script_content = dedent(
        f"""\
        {shebang}

        set -euox pipefail

        if command -v which > /dev/null; then
            command which -a $1 || true
        else
            command -v $1 || true
        fi
        """
    )
    script_digest = await Get(
        Digest,
        CreateDigest([FileContent(script_path, script_content.encode(), is_executable=True)]),
    )

    search_path = create_path_env_var(request.search_path)
    result = await Get(
        ProcessResult,
        # We use a volatile process to force re-run since any binary found on the host system today
        # could be gone tomorrow. Ideally we'd only do this for local processes since all known
        # remoting configurations include a static container image as part of their cache key which
        # automatically avoids this problem. See #10769 for a solution that is less of a tradeoff.
        Process(
            description=f"Searching for `{request.binary_name}` on PATH={search_path}",
            level=LogLevel.DEBUG,
            input_digest=script_digest,
            argv=[script_path, request.binary_name],
            env={"PATH": search_path},
            cache_scope=ProcessCacheScope.PER_RESTART,
        ),
    )

    binary_paths = BinaryPaths(binary_name=request.binary_name)
    found_paths = result.stdout.decode().splitlines()
    if not request.test:
        return dataclasses.replace(binary_paths, paths=[BinaryPath(path) for path in found_paths])

    results = await MultiGet(
        Get(
            FallibleProcessResult,
            Process(
                description=f"Test binary {path}.",
                level=LogLevel.DEBUG,
                argv=[path, *request.test.args],
                cache_scope=ProcessCacheScope.PER_RESTART,
            ),
        )
        for path in found_paths
    )
    return dataclasses.replace(
        binary_paths,
        paths=[
            (
                BinaryPath.fingerprinted(path, result.stdout)
                if request.test.fingerprint_stdout
                else BinaryPath(path, result.stdout.decode())
            )
            for path, result in zip(found_paths, results)
            if result.exit_code == 0
        ],
    )


def rules():
    return collect_rules()
