# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from typing import ClassVar, Iterable, Type, TypeVar

from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSetWithOrigin, Sources, TargetsWithOrigins
from pants.engine.unions import UnionMembership, union
from pants.util.strutil import strip_v2_chroot_path


@dataclass(frozen=True)
class LintResult:
    exit_code: int
    stdout: str
    stderr: str
    linter_name: str

    @staticmethod
    def noop() -> "LintResult":
        return LintResult(exit_code=0, stdout="", stderr="", linter_name="")

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult, *, linter_name: str, strip_chroot_path: bool = False
    ) -> "LintResult":
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return LintResult(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            linter_name=linter_name,
        )


class LinterFieldSet(FieldSetWithOrigin, metaclass=ABCMeta):
    """The fields necessary for a particular linter to work with a target."""

    sources: Sources


_FS = TypeVar("_FS", bound="LinterFieldSet")


@union
class LinterFieldSets(Collection[_FS]):
    """A collection of `FieldSet`s for a particular linter, e.g. a collection of
    `Flake8FieldSet`s."""

    field_set_type: ClassVar[Type[_FS]]


class LintOptions(GoalSubsystem):
    """Lint source code."""

    name = "lint"

    required_union_implementations = (LinterFieldSets,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--per-target-caching",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "Rather than running all targets in a single batch, run each target as a "
                "separate process. Why do this? You'll get many more cache hits. Additionally, for "
                "Python users, if you have some targets that only work with Python 2 and some that "
                "only work with Python 3, `--per-target-caching` will allow you to use the right "
                "interpreter for each target. Why not do this? Linters both have substantial "
                "startup overhead and are cheap to add one additional file to the run. On a cold "
                "cache, it is much faster to use `--no-per-target-caching`. We only recommend "
                "using `--per-target-caching` if you "
                "are using a remote cache, or if you have some Python 2-only targets and "
                "some Python 3-only targets, or if you have benchmarked that this option will be "
                "faster than `--no-per-target-caching` for your use case."
            ),
        )


class Lint(Goal):
    subsystem_cls = LintOptions


@goal_rule
async def lint(
    console: Console,
    targets_with_origins: TargetsWithOrigins,
    options: LintOptions,
    union_membership: UnionMembership,
) -> Lint:
    field_set_collection_types: Iterable[Type[LinterFieldSets]] = union_membership.union_rules[
        LinterFieldSets
    ]

    field_set_collections: Iterable[LinterFieldSets] = tuple(
        field_set_collection_type(
            field_set_collection_type.field_set_type.create(target_with_origin)
            for target_with_origin in targets_with_origins
            if field_set_collection_type.field_set_type.is_valid(target_with_origin.target)
        )
        for field_set_collection_type in field_set_collection_types
    )
    field_set_collections_with_sources: Iterable[FieldSetsWithSources] = await MultiGet(
        Get[FieldSetsWithSources](FieldSetsWithSourcesRequest(field_set_collection))
        for field_set_collection in field_set_collections
    )
    # NB: We must convert back the generic FieldSetsWithSources objects back into their
    # corresponding LinterFieldSets, e.g. back to IsortFieldSets, in order for the union rule to
    # work.
    valid_field_set_collections: Iterable[LinterFieldSets] = tuple(
        field_set_collection_cls(field_set_collection)
        for field_set_collection_cls, field_set_collection in zip(
            field_set_collection_types, field_set_collections_with_sources
        )
        if field_set_collection
    )

    if options.values.per_target_caching:
        results = await MultiGet(
            Get[LintResult](LinterFieldSets, field_set_collection.__class__([field_set]))
            for field_set_collection in valid_field_set_collections
            for field_set in field_set_collection
        )
    else:
        results = await MultiGet(
            Get[LintResult](LinterFieldSets, field_set_collection)
            for field_set_collection in valid_field_set_collections
        )

    if not results:
        return Lint(exit_code=0)

    exit_code = 0
    sorted_results = sorted(results, key=lambda res: res.linter_name)
    for result in sorted_results:
        console.print_stderr(
            f"{console.green('✓')} {result.linter_name} succeeded."
            if result.exit_code == 0
            else f"{console.red('𐄂')} {result.linter_name} failed."
        )
        if result.stdout:
            console.print_stderr(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)
        if result != sorted_results[-1]:
            console.print_stderr("")
        if result.exit_code != 0:
            exit_code = result.exit_code

    return Lint(exit_code)


def rules():
    return [lint]
