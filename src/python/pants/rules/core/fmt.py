# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Tuple, Type

from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    DirectoryToMaterialize,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargetsWithOrigins
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.lint import Linter


@dataclass(frozen=True)
class FmtResult:
    digest: Digest
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> "FmtResult":
        return FmtResult(digest=EMPTY_DIRECTORY_DIGEST, stdout="", stderr="")

    @staticmethod
    def from_execute_process_result(process_result: ExecuteProcessResult) -> "FmtResult":
        return FmtResult(
            digest=process_result.output_directory_digest,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
        )


@dataclass(frozen=True)
class LanguageFmtResults:
    """This collection allows us to safely aggregate multiple `FmtResult`s for a language.

    The `combined_digest` is used to ensure that none of the formatters overwrite each other. The
    language implementation should run each formatter one at a time and pipe the resulting digest of
    one formatter into the next. The `combined_digest` must contain all files for the target,
    including any which were not re-formatted.
    """

    results: Tuple[FmtResult, ...]
    combined_digest: Digest


@dataclass(frozen=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class Formatter(Linter, metaclass=ABCMeta):
    pass


@union
@dataclass(frozen=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class LanguageFormatters(ABC):
    adaptors_with_origins: Tuple[TargetAdaptorWithOrigin, ...]

    @staticmethod
    @abstractmethod
    def belongs_to_language(_: TargetAdaptorWithOrigin) -> bool:
        pass


class FmtOptions(GoalSubsystem):
    """Autoformat source code."""

    # TODO: make this "fmt"
    # Blocked on https://github.com/pantsbuild/pants/issues/8351
    name = "fmt2"

    required_union_implementations = (LanguageFormatters,)


class Fmt(Goal):
    subsystem_cls = FmtOptions


@goal_rule
async def fmt(
    console: Console,
    targets_with_origins: HydratedTargetsWithOrigins,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    adaptors_with_origins = [
        TargetAdaptorWithOrigin.create(target_with_origin.target.adaptor, target_with_origin.origin)
        for target_with_origin in targets_with_origins
        if target_with_origin.target.adaptor.has_sources()
    ]

    all_language_formatters: Iterable[Type[LanguageFormatters]] = union_membership.union_rules[
        LanguageFormatters
    ]
    per_language_results = await MultiGet(
        Get[LanguageFmtResults](LanguageFormatters, language_formatters((adaptor_with_origin,)))
        for adaptor_with_origin in adaptors_with_origins
        for language_formatters in all_language_formatters
        if language_formatters.belongs_to_language(adaptor_with_origin)
    )
    individual_results: List[FmtResult] = list(
        itertools.chain.from_iterable(
            language_result.results for language_result in per_language_results
        )
    )

    if not individual_results:
        return Fmt(exit_code=0)

    # NB: this will fail if there are any conflicting changes, which we want to happen rather than
    # silently having one result override the other. In practicality, this should never happen due
    # to us grouping each language's formatters into a single combined_digest.
    merged_formatted_digest = await Get[Digest](
        DirectoriesToMerge(
            tuple(language_result.combined_digest for language_result in per_language_results)
        )
    )
    workspace.materialize_directory(DirectoryToMaterialize(merged_formatted_digest))
    for result in individual_results:
        if result.stdout:
            console.print_stdout(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)

    # Since the rules to produce FmtResult should use ExecuteRequest, rather than
    # FallibleExecuteProcessRequest, we assume that there were no failures.
    return Fmt(exit_code=0)


def rules():
    return [fmt]
