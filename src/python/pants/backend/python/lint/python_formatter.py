# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from typing import Iterable, List, Optional, Type

from pants.backend.python.lint.python_linter import PYTHON_TARGET_TYPES, PythonLinter
from pants.engine.fs import Digest, Snapshot
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.rules.core.fmt import FmtResult, Formatter, LanguageFmtResults, LanguageFormatters


@union
@dataclass(frozen=True)
class PythonFormatter(Formatter, PythonLinter, metaclass=ABCMeta):
    prior_formatter_result: Optional[Snapshot] = None


@dataclass(frozen=True)
class PythonFormatters(LanguageFormatters):
    @staticmethod
    def belongs_to_language(adaptor_with_origin: TargetAdaptorWithOrigin) -> bool:
        return isinstance(adaptor_with_origin, PYTHON_TARGET_TYPES)


@rule
async def format_python_target(
    python_formatters: PythonFormatters, union_membership: UnionMembership
) -> LanguageFmtResults:
    adaptors_with_origins = python_formatters.adaptors_with_origins
    original_sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            adaptor_with_origin.adaptor for adaptor_with_origin in adaptors_with_origins
        )
    )
    prior_formatter_result = original_sources.snapshot

    results: List[FmtResult] = []
    formatters: Iterable[Type[PythonFormatter]] = union_membership.union_rules[PythonFormatter]
    for formatter in formatters:
        result = await Get[FmtResult](
            PythonFormatter,
            formatter(adaptors_with_origins, prior_formatter_result=prior_formatter_result),
        )
        if result != FmtResult.noop():
            results.append(result)
            prior_formatter_result = await Get[Snapshot](Digest, result.digest)
    return LanguageFmtResults(
        tuple(results), combined_digest=prior_formatter_result.directory_digest
    )


def rules():
    return [format_python_target, UnionRule(LanguageFormatters, PythonFormatters)]
