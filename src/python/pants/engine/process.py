# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union

from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import RootRule, rule
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductDescription:
    value: str


@frozen_after_init
@dataclass(unsafe_hash=True)
class Process:
    argv: Tuple[str, ...]
    description: str
    input_digest: Digest
    working_directory: Optional[str]
    env: Tuple[str, ...]
    append_only_caches: Tuple[str, ...]
    output_files: Tuple[str, ...]
    output_directories: Tuple[str, ...]
    timeout_seconds: Union[int, float]
    jdk_home: Optional[str]
    is_nailgunnable: bool

    def __init__(
        self,
        argv: Iterable[str],
        *,
        description: str,
        input_digest: Digest = EMPTY_DIGEST,
        working_directory: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        append_only_caches: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
        timeout_seconds: Optional[Union[int, float]] = None,
        jdk_home: Optional[str] = None,
        is_nailgunnable: bool = False,
    ) -> None:
        """Request to run a subprocess, similar to subprocess.Popen.

        This process will be hermetic, meaning that it cannot access files and environment variables
        that are not explicitly populated. For example, $PATH will not be defined by default, unless
        populated through the `env` parameter.

        Usually, you will want to provide input files/directories via the parameter `input_digest`. The
        process will then be able to access these paths through relative paths. If you want to give
        multiple input digests, first merge them with `await Get[Digest](MergeDigests)`.

        Often, you will want to capture the files/directories created in the process. To do this, you
        can either set `output_files` or `output_directories`. The specified paths will then be used to
        populate `output_digest` on the `ProcessResult`. If you want to split up this output digest
        into multiple digests, use `await Get[Snapshot](SnapshotSubset)` on the `output_digest`.

        To actually run the process, use `await Get[ProcessResult](Process)` or
        `await Get[FallibleProcessResult](Process)`.

        Example:

            result = await Get[ProcessResult](Process(["/bin/echo", "hello world"], description="demo"))
            assert result.stdout == b"hello world"
        """
        self.argv = tuple(argv)
        self.description = description
        self.input_digest = input_digest
        self.working_directory = working_directory
        self.env = tuple(itertools.chain.from_iterable((env or {}).items()))
        self.append_only_caches = tuple(
            itertools.chain.from_iterable((append_only_caches or {}).items())
        )
        self.output_files = tuple(output_files or ())
        self.output_directories = tuple(output_directories or ())
        # NB: A negative or None time value is normalized to -1 to ease the transfer to Rust.
        self.timeout_seconds = timeout_seconds if timeout_seconds and timeout_seconds > 0 else -1
        self.jdk_home = jdk_home
        self.is_nailgunnable = is_nailgunnable


@frozen_after_init
@dataclass(unsafe_hash=True)
class MultiPlatformProcess:
    # args collects a set of tuples representing platform constraints mapped to a req,
    # just like a dict constructor can.
    platform_constraints: Tuple[str, ...]
    processes: Tuple[Process, ...]

    def __init__(
        self, request_dict: Dict[Tuple[PlatformConstraint, PlatformConstraint], Process],
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
        super().__init__(
            dedent(
                f"""\
                Process '{process_description}' failed with exit code {exit_code}.
                stdout:
                {stdout.decode()}

                stderr:
                {stderr.decode()}
                """
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
            fallible_result.stdout, fallible_result.stderr, fallible_result.output_digest,
        )
    raise ProcessExecutionFailure(
        fallible_result.exit_code,
        fallible_result.stdout,
        fallible_result.stderr,
        description.value,
    )


@rule
def remove_platform_information(res: FallibleProcessResultWithPlatform,) -> FallibleProcessResult:
    return FallibleProcessResult(
        exit_code=res.exit_code,
        stdout=res.stdout,
        stderr=res.stderr,
        output_digest=res.output_digest,
    )


def rules():
    """Creates rules that consume the intrinsic filesystem types."""
    return [
        RootRule(Process),
        RootRule(MultiPlatformProcess),
        upcast_process,
        fallible_to_exec_result_or_raise,
        remove_platform_information,
        get_multi_platform_request_description,
    ]
