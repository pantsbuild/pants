# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union

from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import RootRule, rule
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)

_default_timeout_seconds = 15 * 60


@dataclass(frozen=True)
class ProductDescription:
    value: str


@frozen_after_init
@dataclass(unsafe_hash=True)
class Process:
    """Request for execution with args and snapshots to extract."""

    # TODO: add a method to hack together a `process_executor` invocation command line which
    # reproduces this process execution request to make debugging remote executions effortless!
    argv: Tuple[str, ...]
    input_files: Digest
    description: str
    working_directory: Optional[str]
    env: Tuple[str, ...]
    output_files: Tuple[str, ...]
    output_directories: Tuple[str, ...]
    timeout_seconds: Union[int, float]
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: Digest
    jdk_home: Optional[str]
    is_nailgunnable: bool

    def __init__(
        self,
        argv: Tuple[str, ...],
        *,
        input_files: Digest,
        description: str,
        working_directory: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        output_files: Optional[Tuple[str, ...]] = None,
        output_directories: Optional[Tuple[str, ...]] = None,
        timeout_seconds: Union[int, float] = _default_timeout_seconds,
        unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule: Digest = EMPTY_DIRECTORY_DIGEST,
        jdk_home: Optional[str] = None,
        is_nailgunnable: bool = False,
    ) -> None:
        self.argv = argv
        self.input_files = input_files
        self.description = description
        self.working_directory = working_directory
        self.env = tuple(itertools.chain.from_iterable((env or {}).items()))
        self.output_files = output_files or ()
        self.output_directories = output_directories or ()
        self.timeout_seconds = timeout_seconds
        self.unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule = (
            unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule
        )
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
    """Result of successfully executing a process.

    Requesting one of these will raise an exception if the exit code is non-zero.
    """

    stdout: bytes
    stderr: bytes
    output_directory_digest: Digest


@dataclass(frozen=True)
class FallibleProcessResult:
    """Result of executing a process.

    Requesting one of these will not raise an exception if the exit code is non-zero.
    """

    stdout: bytes
    stderr: bytes
    exit_code: int
    output_directory_digest: Digest


@dataclass(frozen=True)
class FallibleProcessResultWithPlatform:
    """Result of executing a process.

    Contains information about what platform a request ran on.
    """

    stdout: bytes
    stderr: bytes
    exit_code: int
    output_directory_digest: Digest
    platform: Platform


class ProcessExecutionFailure(Exception):
    """Used to denote that a process exited, but was unsuccessful in some way.

    For example, exiting with a non-zero code.
    """

    MSG_FMT = """process '{desc}' failed with exit code {code}.
stdout:
{stdout}
stderr:
{stderr}
"""

    def __init__(self, exit_code, stdout, stderr, process_description):
        # These are intentionally "public" members.
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

        msg = self.MSG_FMT.format(
            desc=process_description, code=exit_code, stdout=stdout.decode(), stderr=stderr.decode()
        )

        super().__init__(msg)


@rule
def get_multi_platform_request_description(req: MultiPlatformProcess,) -> ProductDescription:
    return req.product_description


@rule
def upcast_process(req: Process,) -> MultiPlatformProcess:
    """This rule allows an Process to be run as a platform compatible MultiPlatformProcess."""
    return MultiPlatformProcess({(PlatformConstraint.none, PlatformConstraint.none): req})


@rule
def fallible_to_exec_result_or_raise(
    fallible_result: FallibleProcessResult, description: ProductDescription
) -> ProcessResult:
    """Converts a FallibleProcessResult to a ProcessResult or raises an error."""

    if fallible_result.exit_code == 0:
        return ProcessResult(
            fallible_result.stdout, fallible_result.stderr, fallible_result.output_directory_digest,
        )
    else:
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
        output_directory_digest=res.output_directory_digest,
    )


def create_process_rules():
    """Creates rules that consume the intrinsic filesystem types."""
    return [
        RootRule(Process),
        RootRule(MultiPlatformProcess),
        upcast_process,
        fallible_to_exec_result_or_raise,
        remove_platform_information,
        get_multi_platform_request_description,
    ]
