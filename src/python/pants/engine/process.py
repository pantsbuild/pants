# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
from typing import TYPE_CHECKING, Dict, Iterable, Mapping, Optional, Tuple, Union, cast
from uuid import UUID

from pants.base.exception_sink import ExceptionSink
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent
from pants.engine.internals.selectors import MultiGet
from pants.engine.internals.uuid import UUIDRequest, UUIDScope
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import Get, collect_rules, rule, side_effecting
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import create_path_env_var, pluralize

if TYPE_CHECKING:
    from pants.engine.internals.scheduler import SchedulerSession


logger = logging.getLogger(__name__)


BASH_SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


@dataclass(frozen=True)
class ProductDescription:
    value: str


@frozen_after_init
@dataclass(unsafe_hash=True)
class Process:
    argv: Tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest
    working_directory: Optional[str]
    env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]
    output_files: Tuple[str, ...]
    output_directories: Tuple[str, ...]
    timeout_seconds: Union[int, float]
    jdk_home: Optional[str]
    is_nailgunnable: bool
    execution_slot_variable: Optional[str]
    cache_failures: bool

    def __init__(
        self,
        argv: Iterable[str],
        *,
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest = EMPTY_DIGEST,
        working_directory: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        append_only_caches: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
        timeout_seconds: Optional[Union[int, float]] = None,
        jdk_home: Optional[str] = None,
        is_nailgunnable: bool = False,
        execution_slot_variable: Optional[str] = None,
        cache_failures: bool = False,
    ) -> None:
        """Request to run a subprocess, similar to subprocess.Popen.

        This process will be hermetic, meaning that it cannot access files and environment variables
        that are not explicitly populated. For example, $PATH will not be defined by default, unless
        populated through the `env` parameter.

        Usually, you will want to provide input files/directories via the parameter `input_digest`. The
        process will then be able to access these paths through relative paths. If you want to give
        multiple input digests, first merge them with `await Get(Digest, MergeDigests)`.

        Often, you will want to capture the files/directories created in the process. To do this, you
        can either set `output_files` or `output_directories`. The specified paths will then be used to
        populate `output_digest` on the `ProcessResult`. If you want to split up this output digest
        into multiple digests, use `await Get(Digest, DigestSubset)` on the `output_digest`.

        To actually run the process, use `await Get(ProcessResult, Process)` or
        `await Get(FallibleProcessResult, Process)`.

        Example:

            result = await Get(ProcessResult, Process(["/bin/echo", "hello world"], description="demo"))
            assert result.stdout == b"hello world"
        """
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
        self.cache_failures = cache_failures


@frozen_after_init
@dataclass(unsafe_hash=True)
class MultiPlatformProcess:
    # args collects a set of tuples representing platform constraints mapped to a req,
    # just like a dict constructor can.
    platform_constraints: Tuple[str, ...]
    processes: Tuple[Process, ...]

    def __init__(
        self,
        request_dict: Dict[Tuple[PlatformConstraint, PlatformConstraint], Process],
    ) -> None:
        if len(request_dict) == 0:
            raise ValueError("At least one platform constrained Process must be passed.")
        validated_constraints = tuple(
            constraint.value
            for pair in request_dict.keys()
            for constraint in pair
            if PlatformConstraint(constraint.value)
        )
        if len({req.description for req in request_dict.values()}) != 1:
            raise ValueError(
                f"The `description` of all processes in a {MultiPlatformProcess.__name__} must be identical."
            )

        self.platform_constraints = validated_constraints
        self.processes = tuple(request_dict.values())

    @property
    def product_description(self) -> ProductDescription:
        # we can safely extract the first description because we guarantee that at
        # least one request exists and that all of their descriptions are the same
        # in __new__
        return ProductDescription(self.processes[0].description)


@dataclass(frozen=True)
class ProcessResult:
    """Result of executing a process which should not fail.

    If the process has a non-zero exit code, this will raise an exception, unlike
    FallibleProcessResult.
    """

    stdout: bytes
    stderr: bytes
    output_digest: Digest


@dataclass(frozen=True)
class FallibleProcessResult:
    """Result of executing a process which might fail.

    If the process has a non-zero exit code, this will not raise an exception, unlike ProcessResult.
    """

    stdout: bytes
    stderr: bytes
    exit_code: int
    output_digest: Digest


@dataclass(frozen=True)
class FallibleProcessResultWithPlatform:
    """Result of executing a process which might fail, along with the platform it ran on."""

    stdout: bytes
    stderr: bytes
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
    return MultiPlatformProcess({(PlatformConstraint.none, PlatformConstraint.none): req})


@rule
def fallible_to_exec_result_or_raise(
    fallible_result: FallibleProcessResult, description: ProductDescription
) -> ProcessResult:
    """Converts a FallibleProcessResult to a ProcessResult or raises an error."""

    if fallible_result.exit_code == 0:
        return ProcessResult(
            fallible_result.stdout,
            fallible_result.stderr,
            fallible_result.output_digest,
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
        stderr=res.stderr,
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
    hermetic_env: bool
    forward_signals_to_process: bool

    def __init__(
        self,
        argv: Iterable[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        input_digest: Digest = EMPTY_DIGEST,
        run_in_workspace: bool = False,
        hermetic_env: bool = True,
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
        self.hermetic_env = hermetic_env
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
        cls, process: Process, *, hermetic_env: bool = True, forward_signals_to_process: bool = True
    ) -> "InteractiveProcess":
        return InteractiveProcess(
            argv=process.argv,
            env=process.env,
            input_digest=process.input_digest,
            hermetic_env=hermetic_env,
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

    search_path: Tuple[str, ...]
    binary_name: str
    test: Optional[BinaryPathTest]

    def __init__(
        self,
        *,
        search_path: Iterable[str],
        binary_name: str,
        test: Optional[BinaryPathTest] = None,
    ) -> None:
        self.search_path = tuple(OrderedSet(search_path))
        self.binary_name = binary_name
        self.test = test


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryPath:
    path: str
    fingerprint: str

    def __init__(self, path: str, fingerprint: Optional[str] = None) -> None:
        self.path = path
        self.fingerprint = self._fingerprint() if fingerprint is None else fingerprint

    @staticmethod
    def _fingerprint(content: Optional[Union[bytes, bytearray, memoryview]] = None) -> str:
        hasher = hashlib.sha256() if content is None else hashlib.sha256(content)
        return hasher.hexdigest()

    @classmethod
    def fingerprinted(
        cls, path: str, representative_content: Union[bytes, bytearray, memoryview]
    ) -> "BinaryPath":
        return cls(path, fingerprint=cls._fingerprint(representative_content))


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryPaths(EngineAwareReturnType):
    binary_name: str
    paths: Tuple[BinaryPath, ...]

    def __init__(self, binary_name: str, paths: Optional[Iterable[BinaryPath]] = None):
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
    def first_path(self) -> Optional[BinaryPath]:
        """Return the first path to the binary that was discovered, if any."""
        return next(iter(self.paths), None)


class ProcessScope(Enum):
    PER_CALL = UUIDScope.PER_CALL
    PER_SESSION = UUIDScope.PER_SESSION


@dataclass(frozen=True)
class UncacheableProcess:
    """Ensures the wrapped Process will be run once per scope and its results never re-used.

    By default the scope is PER_CALL which ensures the Process is re-run on every call.
    """

    process: Process
    scope: ProcessScope = ProcessScope.PER_CALL


@rule
async def make_process_uncacheable(uncacheable_process: UncacheableProcess) -> Process:
    uuid = await Get(
        UUID, UUIDRequest, UUIDRequest.scoped(cast(UUIDScope, uncacheable_process.scope.value))
    )

    process = uncacheable_process.process
    env = dict(process.env)

    # This is a slightly hacky way to force the process to run: since the env var
    #  value is unique, this input combination will never have been seen before,
    #  and therefore never cached. The two downsides are:
    #  1. This leaks into the process' environment, albeit with a funky var name that is
    #     unlikely to cause problems in practice.
    #  2. This run will be cached even though it can never be re-used.
    # TODO: A more principled way of forcing rules to run?
    env["__PANTS_FORCE_PROCESS_RUN__"] = str(uuid)

    return dataclasses.replace(process, env=FrozenDict(env))


class BinaryNotFoundError(EnvironmentError):
    def __init__(
        self,
        request: BinaryPathRequest,
        *,
        rationale: Optional[str] = None,
        alternative_solution: Optional[str] = None,
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


@rule(desc="Find binary path", level=LogLevel.DEBUG)
async def find_binary(request: BinaryPathRequest) -> BinaryPaths:
    # If we are not already locating bash, recurse to locate bash to use it as an absolute path in
    # our shebang. This avoids mixing locations that we would search for bash into the search paths
    # of the request we are servicing.
    # TODO(#10769): Replace this script with a statically linked native binary so we don't
    #  depend on either /bin/bash being available on the Process host.
    if request.binary_name == "bash":
        shebang = "#!/usr/bin/env bash"
    else:
        bash_request = BinaryPathRequest(binary_name="bash", search_path=BASH_SEARCH_PATHS)
        bash_paths = await Get(BinaryPaths, BinaryPathRequest, bash_request)
        if not bash_paths.first_path:
            raise BinaryNotFoundError(bash_request, rationale="use it to locate other executables")
        shebang = f"#!{bash_paths.first_path.path}"

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
        # automatically avoids this problem.
        UncacheableProcess(
            Process(
                description=f"Searching for `{request.binary_name}` on PATH={search_path}",
                level=LogLevel.DEBUG,
                input_digest=script_digest,
                argv=[script_path, request.binary_name],
                env={"PATH": search_path},
            ),
            scope=ProcessScope.PER_SESSION,
        ),
    )

    binary_paths = BinaryPaths(binary_name=request.binary_name)
    found_paths = result.stdout.decode().splitlines()
    if not request.test:
        return dataclasses.replace(binary_paths, paths=[BinaryPath(path) for path in found_paths])

    results = await MultiGet(
        Get(
            FallibleProcessResult,
            UncacheableProcess(
                Process(
                    description=f"Test binary {path}.",
                    level=LogLevel.DEBUG,
                    argv=[path, *request.test.args],
                ),
                scope=ProcessScope.PER_SESSION,
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
