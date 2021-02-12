# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar, Iterable, List, Optional, Tuple, Type, TypeVar, cast

from pants.core.util_rules.filter_empty_sources import TargetsWithSources, TargetsWithSourcesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, _uncacheable_rule, collect_rules, goal_rule
from pants.engine.target import Field, Target, Targets
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel
from pants.util.strutil import strip_v2_chroot_path

_F = TypeVar("_F", bound="FmtResult")


@dataclass(frozen=True)
class FmtResult:
    input: Digest
    output: Digest
    stdout: str
    stderr: str
    formatter_name: str

    @classmethod
    def skip(cls: Type[_F], *, formatter_name: str) -> _F:
        return cls(
            input=EMPTY_DIGEST,
            output=EMPTY_DIGEST,
            stdout="",
            stderr="",
            formatter_name=formatter_name,
        )

    @classmethod
    def from_process_result(
        cls,
        process_result: ProcessResult,
        *,
        original_digest: Digest,
        formatter_name: str,
        strip_chroot_path: bool = False,
    ) -> FmtResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return cls(
            input=original_digest,
            output=process_result.output_digest,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            formatter_name=formatter_name,
        )

    @property
    def skipped(self) -> bool:
        return (
            self.input == EMPTY_DIGEST
            and self.output == EMPTY_DIGEST
            and not self.stdout
            and not self.stderr
        )

    @property
    def did_change(self) -> bool:
        return self.output != self.input


@dataclass(frozen=True)
class EnrichedFmtResult(FmtResult, EngineAwareReturnType):
    """A `FmtResult` that is enriched for the sake of logging results as they come in.

    Plugin authors only need to return `FmtResult`, and a rule will upcast those into
    `EnrichedFmtResult`.
    """

    def level(self) -> Optional[LogLevel]:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.WARN if self.did_change else LogLevel.INFO

    def message(self) -> Optional[str]:
        if self.skipped:
            return f"{self.formatter_name} skipped."
        message = "made changes." if self.did_change else "made no changes."
        output = ""
        if self.stdout:
            output += f"\n{self.stdout}"
        if self.stderr:
            output += f"\n{self.stderr}"
        if output:
            output = f"{output.rstrip()}\n\n"
        return f"{self.formatter_name} {message}{output}"


# NB: We mark this uncachable to ensure that the results are always streamed, even if the
# underlying FmtResult is memoized. This rule is very cheap, so there's little performance hit.
@_uncacheable_rule(desc="fmt")
async def enrich_fmt_result(result: FmtResult) -> EnrichedFmtResult:
    return EnrichedFmtResult(
        input=result.input,
        output=result.output,
        stdout=result.stdout,
        stderr=result.stderr,
        formatter_name=result.formatter_name,
    )


@union
@dataclass(frozen=True)
class LanguageFmtTargets:
    """All the targets that belong together as one language, e.g. all Python targets.

    This allows us to group distinct formatters by language as a performance optimization. Within a
    language, each formatter must run sequentially to not overwrite the previous formatter; but
    across languages, it is safe to run in parallel.
    """

    required_fields: ClassVar[Tuple[Type[Field], ...]]

    targets: Targets

    @classmethod
    def belongs_to_language(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)


@dataclass(frozen=True)
class LanguageFmtResults:
    """This collection allows us to safely aggregate multiple `FmtResult`s for a language.

    The `output` digest is used to ensure that none of the formatters overwrite each other. The
    language implementation should run each formatter one at a time and pipe the resulting digest of
    one formatter into the next. The `input` and `output` digests must contain all files for the
    target(s), including any which were not re-formatted.
    """

    results: Tuple[FmtResult, ...]
    input: Digest
    output: Digest

    @property
    def did_change(self) -> bool:
        return self.input != self.output


class FmtSubsystem(GoalSubsystem):
    name = "fmt"
    help = "Autoformat source code."

    required_union_implementations = (LanguageFmtTargets,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--per-file-caching",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "Rather than formatting all files in a single batch, format each file as a "
                "separate process.\n\nWhy do this? You'll get many more cache hits. Why not do "
                "this? Formatters both have substantial startup overhead and are cheap to add one "
                "additional file to the run. On a cold cache, it is much faster to use "
                "`--no-per-file-caching`.\n\nWe only recommend using `--per-file-caching` if you "
                "are using a remote cache or if you have benchmarked that this option will be "
                "faster than `--no-per-file-caching` for your use case."
            ),
        )

    @property
    def per_file_caching(self) -> bool:
        return cast(bool, self.options.per_file_caching)


class Fmt(Goal):
    subsystem_cls = FmtSubsystem


@goal_rule
async def fmt(
    console: Console,
    targets: Targets,
    fmt_subsystem: FmtSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    language_target_collection_types = union_membership[LanguageFmtTargets]
    language_target_collections: Iterable[LanguageFmtTargets] = tuple(
        language_target_collection_type(
            Targets(
                target
                for target in targets
                if language_target_collection_type.belongs_to_language(target)
            )
        )
        for language_target_collection_type in language_target_collection_types
    )
    targets_with_sources: Iterable[TargetsWithSources] = await MultiGet(
        Get(
            TargetsWithSources,
            TargetsWithSourcesRequest(language_target_collection.targets),
        )
        for language_target_collection in language_target_collections
    )
    # NB: We must convert back the generic TargetsWithSources objects back into their
    # corresponding LanguageFmtTargets, e.g. back to PythonFmtTargets, in order for the union
    # rule to work.
    valid_language_target_collections: Iterable[LanguageFmtTargets] = tuple(
        language_target_collection_cls(
            Targets(
                target
                for target in language_target_collection.targets
                if target in language_targets_with_sources
            )
        )
        for language_target_collection_cls, language_target_collection, language_targets_with_sources in zip(
            language_target_collection_types, language_target_collections, targets_with_sources
        )
        if language_targets_with_sources
    )

    if fmt_subsystem.per_file_caching:
        per_language_results = await MultiGet(
            Get(
                LanguageFmtResults,
                LanguageFmtTargets,
                language_target_collection.__class__(Targets([target])),
            )
            for language_target_collection in valid_language_target_collections
            for target in language_target_collection.targets
        )
    else:
        per_language_results = await MultiGet(
            Get(LanguageFmtResults, LanguageFmtTargets, language_target_collection)
            for language_target_collection in valid_language_target_collections
        )

    individual_results: List[FmtResult] = list(
        itertools.chain.from_iterable(
            language_result.results for language_result in per_language_results
        )
    )

    if not individual_results:
        return Fmt(exit_code=0)

    changed_digests = tuple(
        language_result.output
        for language_result in per_language_results
        if language_result.did_change
    )
    if changed_digests:
        # NB: this will fail if there are any conflicting changes, which we want to happen rather
        # than silently having one result override the other. In practice, this should never
        # happen due to us grouping each language's formatters into a single digest.
        merged_formatted_digest = await Get(Digest, MergeDigests(changed_digests))
        workspace.write_digest(merged_formatted_digest)

    if individual_results:
        console.print_stderr("")

    # We group all results for the same formatter so that we can give one final status in the
    # summary. This is only relevant if there were multiple results because of
    # `--per-file-caching`.
    formatter_to_results = defaultdict(set)
    for result in individual_results:
        formatter_to_results[result.formatter_name].add(result)

    for formatter, results in sorted(formatter_to_results.items()):
        if any(result.did_change for result in results):
            sigil = console.red("𐄂")
            status = "made changes"
        elif all(result.skipped for result in results):
            sigil = console.yellow("-")
            status = "skipped"
        else:
            sigil = console.green("✓")
            status = "made no changes"
        console.print_stderr(f"{sigil} {formatter} {status}.")

    # Since the rules to produce FmtResult should use ExecuteRequest, rather than
    # FallibleProcess, we assume that there were no failures.
    return Fmt(exit_code=0)


def rules():
    return collect_rules()
