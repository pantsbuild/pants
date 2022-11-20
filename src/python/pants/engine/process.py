# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from pants.engine.engine_aware import SideEffecting
from pants.engine.fs import EMPTY_DIGEST, Digest, FileDigest
from pants.engine.internals.native_engine import (  # noqa: F401
    ProcessConfigFromEnvironment as ProcessConfigFromEnvironment,
)
from pants.engine.internals.session import RunId
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.option.global_options import KeepSandboxes
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductDescription:
    value: str


class ProcessCacheScope(Enum):
    # Cached in all locations, regardless of success or failure.
    ALWAYS = "always"
    # Cached in all locations, but only if the process exits successfully.
    SUCCESSFUL = "successful"
    # Cached only in memory (i.e. memoized in pantsd), but never persistently, regardless of
    # success vs. failure.
    PER_RESTART_ALWAYS = "per_restart_always"
    # Cached only in memory (i.e. memoized in pantsd), but never persistently, and only if
    # successful.
    PER_RESTART_SUCCESSFUL = "per_restart_successful"
    # Will run once per Session, i.e. once per run of Pants. This happens because the engine
    # de-duplicates identical work; the process is neither memoized in memory nor cached to disk.
    PER_SESSION = "per_session"


@frozen_after_init
@dataclass(unsafe_hash=True)
class Process:
    argv: tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    input_digest: Digest
    immutable_input_digests: FrozenDict[str, Digest]
    use_nailgun: tuple[str, ...]
    working_directory: str | None
    env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    timeout_seconds: int | float
    jdk_home: str | None
    execution_slot_variable: str | None
    concurrency_available: int
    cache_scope: ProcessCacheScope
    remote_cache_speculation_delay_millis: int

    def __init__(
        self,
        argv: Iterable[str],
        *,
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest = EMPTY_DIGEST,
        immutable_input_digests: Mapping[str, Digest] | None = None,
        use_nailgun: Iterable[str] = (),
        working_directory: str | None = None,
        env: Mapping[str, str] | None = None,
        append_only_caches: Mapping[str, str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        timeout_seconds: int | float | None = None,
        jdk_home: str | None = None,
        execution_slot_variable: str | None = None,
        concurrency_available: int = 0,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
        remote_cache_speculation_delay_millis: int = 0,
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
        self.immutable_input_digests = FrozenDict(immutable_input_digests or {})
        self.use_nailgun = tuple(use_nailgun)
        self.working_directory = working_directory
        self.env = FrozenDict(env or {})
        self.append_only_caches = FrozenDict(append_only_caches or {})
        self.output_files = tuple(output_files or ())
        self.output_directories = tuple(output_directories or ())
        # NB: A negative or None time value is normalized to -1 to ease the transfer to Rust.
        self.timeout_seconds = timeout_seconds if timeout_seconds and timeout_seconds > 0 else -1
        self.jdk_home = jdk_home
        self.execution_slot_variable = execution_slot_variable
        self.concurrency_available = concurrency_available
        self.cache_scope = cache_scope
        self.remote_cache_speculation_delay_millis = remote_cache_speculation_delay_millis


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
    platform: Platform
    metadata: ProcessResultMetadata = field(compare=False, hash=False)


@frozen_after_init
@dataclass(unsafe_hash=True)
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
    platform: Platform
    metadata: ProcessResultMetadata = field(compare=False, hash=False)


@dataclass(frozen=True)
class ProcessResultMetadata:
    """Metadata for a ProcessResult, which is not included in its definition of equality."""

    class Source(Enum):
        RAN_LOCALLY = "ran_locally"
        RAN_REMOTELY = "ran_remotely"
        HIT_LOCALLY = "hit_locally"
        HIT_REMOTELY = "hit_remotely"
        MEMOIZED = "memoized"

    # The execution time of the process, in milliseconds, or None if it could not be captured
    # (since remote execution does not guarantee its availability).
    total_elapsed_ms: int | None
    # Whether the ProcessResult (when it was created in the attached run_id) came from the local
    # or remote cache, or ran locally or remotely. See the `self.source` method.
    _source: str
    # The run_id in which a ProcessResult was created. See the `self.source` method.
    source_run_id: int

    def source(self, current_run_id: RunId) -> Source:
        """Given the current run_id, return the calculated "source" of the ProcessResult.

        If a ProcessResult is consumed in any run_id other than the one it was created in, the its
        source implicitly becomes memoization, since the result was re-used in a new run without
        being recreated.
        """
        return (
            self.Source(self._source)
            if self.source_run_id == current_run_id
            else self.Source.MEMOIZED
        )


class ProcessExecutionFailure(Exception):
    """Used to denote that a process exited, but was unsuccessful in some way.

    For example, exiting with a non-zero code.
    """

    def __init__(
        self,
        exit_code: int,
        stdout: bytes,
        stderr: bytes,
        process_description: str,
        *,
        keep_sandboxes: KeepSandboxes,
    ) -> None:
        # These are intentionally "public" members.
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

        def try_decode(content: bytes) -> str:
            try:
                return content.decode()
            except ValueError:
                content_repr = repr(stdout)
                return f"{content_repr[:256]}..." if len(content_repr) > 256 else content_repr

        # NB: We don't use dedent on a single format string here because it would attempt to
        # interpret the stdio content.
        err_strings = [
            f"Process '{process_description}' failed with exit code {exit_code}.",
            "stdout:",
            try_decode(stdout),
            "stderr:",
            try_decode(stderr),
        ]
        if keep_sandboxes == KeepSandboxes.never:
            err_strings.append(
                "\n\nUse `--keep-sandboxes=on_failure` to preserve the process chroot for inspection."
            )
        super().__init__("\n".join(err_strings))


@rule
def get_multi_platform_request_description(req: Process) -> ProductDescription:
    return ProductDescription(req.description)


@rule
def fallible_to_exec_result_or_raise(
    fallible_result: FallibleProcessResult,
    description: ProductDescription,
    keep_sandboxes: KeepSandboxes,
) -> ProcessResult:
    """Converts a FallibleProcessResult to a ProcessResult or raises an error."""

    if fallible_result.exit_code == 0:
        return ProcessResult(
            stdout=fallible_result.stdout,
            stdout_digest=fallible_result.stdout_digest,
            stderr=fallible_result.stderr,
            stderr_digest=fallible_result.stderr_digest,
            output_digest=fallible_result.output_digest,
            platform=fallible_result.platform,
            metadata=fallible_result.metadata,
        )
    raise ProcessExecutionFailure(
        fallible_result.exit_code,
        fallible_result.stdout,
        fallible_result.stderr,
        description.value,
        keep_sandboxes=keep_sandboxes,
    )


@dataclass(frozen=True)
class InteractiveProcessResult:
    exit_code: int


@frozen_after_init
@dataclass(unsafe_hash=True)
class InteractiveProcess(SideEffecting):
    # NB: Although InteractiveProcess supports only some of the features of Process, we construct an
    # underlying Process instance to improve code reuse.
    process: Process
    run_in_workspace: bool
    forward_signals_to_process: bool
    restartable: bool
    keep_sandboxes: KeepSandboxes

    def __init__(
        self,
        argv: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        input_digest: Digest = EMPTY_DIGEST,
        run_in_workspace: bool = False,
        forward_signals_to_process: bool = True,
        restartable: bool = False,
        append_only_caches: Mapping[str, str] | None = None,
        immutable_input_digests: Mapping[str, Digest] | None = None,
        keep_sandboxes: KeepSandboxes = KeepSandboxes.never,
    ) -> None:
        """Request to run a subprocess in the foreground, similar to subprocess.run().

        Unlike `Process`, the result will not be cached.

        To run the process, use `await Effect(InteractiveProcessResult, InteractiveProcess(..))`
        in a `@goal_rule`.

        `forward_signals_to_process` controls whether pants will allow a SIGINT signal
        sent to a process by hitting Ctrl-C in the terminal to actually reach the process,
        or capture that signal itself, blocking it from the process.
        """
        self.process = Process(
            argv,
            description="Interactive process",
            env=env,
            input_digest=input_digest,
            append_only_caches=append_only_caches,
            immutable_input_digests=immutable_input_digests,
        )
        self.run_in_workspace = run_in_workspace
        self.forward_signals_to_process = forward_signals_to_process
        self.restartable = restartable
        self.keep_sandboxes = keep_sandboxes

    @classmethod
    def from_process(
        cls,
        process: Process,
        *,
        forward_signals_to_process: bool = True,
        restartable: bool = False,
    ) -> InteractiveProcess:
        return InteractiveProcess(
            argv=process.argv,
            env=process.env,
            input_digest=process.input_digest,
            forward_signals_to_process=forward_signals_to_process,
            restartable=restartable,
            append_only_caches=process.append_only_caches,
            immutable_input_digests=process.immutable_input_digests,
        )


def rules():
    return collect_rules()
