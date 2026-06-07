# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.process import Process, ProcessCacheScope, ProcessConcurrency
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Subprocess:
    """One in a list of subprocesses to run sequentially in the same Process invocation."""

    # The subprocess can either provide argv or a pre-joined command string, but not both.
    command: str | None
    argv: Iterable[str]
    input_digest: Digest
    immutable_input_digests: FrozenDict[str, Digest]
    env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]
    output_files: Iterable[str]
    output_directories: Iterable[str]

    def __init__(
        self,
        *,
        command: str | None = None,
        argv: Iterable[str] | None = None,
        input_digest: Digest = EMPTY_DIGEST,
        immutable_input_digests: Mapping[str, Digest] | None = None,
        env: Mapping[str, str] | None = None,
        append_only_caches: Mapping[str, str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
    ) -> None:
        if (command is None and argv is None) or (command is not None and argv is not None):
            raise ValueError("Exactly one of command and argv must be specified.")
        if isinstance(argv, str):
            raise ValueError("argv must be a sequence of strings, but was a single string.")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "argv", tuple(argv or []))
        object.__setattr__(self, "input_digest", input_digest)
        object.__setattr__(
            self, "immutable_input_digests", FrozenDict(immutable_input_digests or {})
        )
        object.__setattr__(self, "env", FrozenDict(env or {}))
        object.__setattr__(self, "append_only_caches", FrozenDict(append_only_caches or {}))
        object.__setattr__(self, "output_files", tuple(output_files or ()))
        object.__setattr__(self, "output_directories", tuple(output_directories or ()))

    def get_command(self) -> str:
        if self.command is None:
            return shlex.join(self.argv)
        return self.command


@dataclass(frozen=True)
class CompositeProcess:
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    subprocesses: tuple[Subprocess, ...]
    use_nailgun: tuple[str, ...]
    working_directory: str | None
    timeout_seconds: int | float
    jdk_home: str | None
    execution_slot_variable: str | None
    concurrency_available: int
    concurrency: ProcessConcurrency | None
    cache_scope: ProcessCacheScope
    remote_cache_speculation_delay_millis: int
    attempt: int

    @classmethod
    def from_process(cls, proc: Process) -> CompositeProcess:
        """Create a CompositeProcess from a Process.

        The returned CompositeProcess will act exactly as the Process would: the Process's
        field values will be set on the CompositeProcess's fields or on the fields of its single
        Subprocess, as appropriate.
        """
        return cls(
            subprocesses=[
                Subprocess(
                    argv=proc.argv,
                    input_digest=proc.input_digest,
                    immutable_input_digests=proc.immutable_input_digests,
                    env=proc.env,
                    append_only_caches=proc.append_only_caches,
                    output_files=proc.output_files,
                    output_directories=proc.output_directories,
                )
            ],
            description=proc.description,
            level=proc.level,
            use_nailgun=proc.use_nailgun,
            working_directory=proc.working_directory,
            timeout_seconds=proc.timeout_seconds,
            jdk_home=proc.jdk_home,
            execution_slot_variable=proc.execution_slot_variable,
            concurrency_available=proc.concurrency_available,
            concurrency=proc.concurrency,
            cache_scope=proc.cache_scope,
            remote_cache_speculation_delay_millis=proc.remote_cache_speculation_delay_millis,
            attempt=proc.attempt,
        )

    def __init__(
        self,
        subprocesses: Iterable[Subprocess],
        *,
        description: str,
        level: LogLevel = LogLevel.INFO,
        use_nailgun: Iterable[str] = (),
        working_directory: str | None = None,
        timeout_seconds: int | float | None = None,
        jdk_home: str | None = None,
        execution_slot_variable: str | None = None,
        concurrency_available: int = 0,
        concurrency: ProcessConcurrency | None = None,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
        remote_cache_speculation_delay_millis: int = 0,
        attempt: int = 0,
    ) -> None:
        """A sequence of subprocesses to run serially under a single Process."""
        object.__setattr__(self, "subprocesses", tuple(subprocesses))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "level", level)

        object.__setattr__(self, "use_nailgun", tuple(use_nailgun))
        object.__setattr__(self, "working_directory", working_directory)
        # NB: A negative or None time value is normalized to -1 to ease the transfer to Rust.
        object.__setattr__(
            self,
            "timeout_seconds",
            timeout_seconds if timeout_seconds and timeout_seconds > 0 else -1,
        )
        object.__setattr__(self, "jdk_home", jdk_home)
        object.__setattr__(self, "execution_slot_variable", execution_slot_variable)
        object.__setattr__(self, "concurrency_available", concurrency_available)
        object.__setattr__(self, "concurrency", concurrency)
        object.__setattr__(self, "cache_scope", cache_scope)
        object.__setattr__(
            self, "remote_cache_speculation_delay_millis", remote_cache_speculation_delay_millis
        )
        object.__setattr__(self, "attempt", attempt)

    def prepend_subprocesses(self, subprocesses: Iterable[Subprocess]) -> CompositeProcess:
        return dataclasses.replace(self, subprocesses=(*subprocesses, *self.subprocesses))

    def append_subprocesses(self, subprocesses: Iterable[Subprocess]) -> CompositeProcess:
        return dataclasses.replace(self, subprocesses=(*self.subprocesses, *subprocesses))


@rule
async def composite_process_to_process(
    composite_process: CompositeProcess, bash_binary: BashBinary
) -> Process:
    subprocs = composite_process.subprocesses
    command = "\n".join(subproc.get_command() for subproc in subprocs)
    input_digest = await merge_digests(MergeDigests([subproc.input_digest for subproc in subprocs]))

    immutable_input_digests: dict[str, Digest] = {}
    for subproc in subprocs:
        for path, digest in subproc.immutable_input_digests.items():
            if path in immutable_input_digests and immutable_input_digests[path] != digest:
                raise ValueError(
                    "Multiple Subprocess in the same CompositeProcess had "
                    f"immutable_input_digests with the path {path} and different digests"
                )
            immutable_input_digests[path] = digest

    env: dict[str, str] = {}
    for subproc in subprocs:
        for name, val in subproc.env.items():
            if name in env and env[name] != val:
                raise ValueError(
                    "Multiple Subprocess in the same CompositeProcess set the env var "
                    f"{name}, to different values"
                )
            env[name] = val

    append_only_caches: dict[str, str] = {}
    for subproc in subprocs:
        for cache_name, cache_dir in subproc.append_only_caches.items():
            if cache_name in append_only_caches and append_only_caches[cache_name] != cache_dir:
                raise ValueError(
                    "Multiple Subprocess in the same CompositeProcess had  "
                    f"append_only_caches with the name {cache_name} and different values"
                )
            append_only_caches[cache_name] = cache_dir

    return Process(
        argv=(bash_binary.path, "-c", command),
        description=composite_process.description,
        level=composite_process.level,
        input_digest=input_digest,
        immutable_input_digests=immutable_input_digests,
        use_nailgun=composite_process.use_nailgun,
        working_directory=composite_process.working_directory,
        env=env,
        append_only_caches=append_only_caches,
        output_files=[of for subproc in subprocs for of in subproc.output_files],
        output_directories=[od for subproc in subprocs for od in subproc.output_directories],
        timeout_seconds=composite_process.timeout_seconds,
        jdk_home=composite_process.jdk_home,
        execution_slot_variable=composite_process.execution_slot_variable,
        concurrency_available=composite_process.concurrency_available,
        concurrency=composite_process.concurrency,
        cache_scope=composite_process.cache_scope,
        remote_cache_speculation_delay_millis=composite_process.remote_cache_speculation_delay_millis,
        attempt=composite_process.attempt,
    )


def rules():
    return collect_rules()
