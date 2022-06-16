# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.engine import process
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmProcess:
    """Helper process class used to invoke Helm on a given `input_digest`."""

    argv: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_env: FrozenDict[str, str]
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_append_only_caches: FrozenDict[str, str]
    cache_scope: ProcessCacheScope | None
    output_directories: tuple[str, ...]
    output_files: tuple[str, ...]
    working_directory: str | None

    def __init__(
        self,
        argv: Iterable[str],
        *,
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        output_directories: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_append_only_caches: Mapping[str, str] | None = None,
        cache_scope: ProcessCacheScope | None = None,
        working_directory: str | None = None,
    ):
        self.argv = tuple(argv)
        self.input_digest = input_digest
        self.description = description
        self.level = level
        self.output_directories = tuple(output_directories or ())
        self.output_files = tuple(output_files or ())
        self.extra_env = FrozenDict(extra_env or {})
        self.extra_immutable_input_digests = FrozenDict(extra_immutable_input_digests or {})
        self.extra_append_only_caches = FrozenDict(extra_append_only_caches or {})
        self.cache_scope = cache_scope
        self.working_directory = working_directory


@rule
def helm_process(request: HelmProcess, helm_binary: HelmBinary) -> Process:
    env = {**helm_binary.env, **request.extra_env}

    immutable_input_digests = {
        **helm_binary.immutable_input_digests,
        **request.extra_immutable_input_digests,
    }

    append_only_caches = {**helm_binary.append_only_caches, **request.extra_append_only_caches}

    return Process(
        [helm_binary.path, *request.argv],
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        env=env,
        description=request.description,
        level=request.level,
        append_only_caches=append_only_caches,
        output_directories=request.output_directories,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
        working_directory=request.working_directory,
    )


def rules():
    return [*collect_rules(), *tool.rules(), *process.rules()]
