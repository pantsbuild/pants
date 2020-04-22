# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from typing import ClassVar, Iterable, Type, TypeVar

from pants.core.util_rules.filter_empty_sources import (
    ConfigurationsWithSources,
    ConfigurationsWithSourcesRequest,
)
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import ConfigurationWithOrigin, Sources, TargetsWithOrigins
from pants.engine.unions import UnionMembership, union


@dataclass(frozen=True)
class LintResult:
    exit_code: int
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> "LintResult":
        return LintResult(exit_code=0, stdout="", stderr="")

    @staticmethod
    def from_fallible_process_result(process_result: FallibleProcessResult,) -> "LintResult":
        return LintResult(
            exit_code=process_result.exit_code,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
        )


class LinterConfiguration(ConfigurationWithOrigin, metaclass=ABCMeta):
    """The fields necessary for a particular linter to work with a target."""

    sources: Sources


C = TypeVar("C", bound="LinterConfiguration")


@union
class LinterConfigurations(Collection[C]):
    """A collection of Configurations for a particular linter, e.g. a collection of
    `Flake8Configuration`s."""

    config_type: ClassVar[Type[C]]


class LintOptions(GoalSubsystem):
    """Lint source code."""

    name = "lint"

    required_union_implementations = (LinterConfigurations,)

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
    config_collection_types: Iterable[Type[LinterConfigurations]] = union_membership.union_rules[
        LinterConfigurations
    ]

    config_collections: Iterable[LinterConfigurations] = tuple(
        config_collection_type(
            config_collection_type.config_type.create(target_with_origin)
            for target_with_origin in targets_with_origins
            if config_collection_type.config_type.is_valid(target_with_origin.target)
        )
        for config_collection_type in config_collection_types
    )
    config_collections_with_sources: Iterable[ConfigurationsWithSources] = await MultiGet(
        Get[ConfigurationsWithSources](ConfigurationsWithSourcesRequest(config_collection))
        for config_collection in config_collections
    )
    # NB: We must convert back the generic ConfigurationsWithSources objects back into their
    # corresponding LinterConfigurations, e.g. back to IsortConfigurations, in order for the union
    # rule to work.
    valid_config_collections: Iterable[LinterConfigurations] = tuple(
        config_collection_cls(config_collection)
        for config_collection_cls, config_collection in zip(
            config_collection_types, config_collections_with_sources
        )
        if config_collection
    )

    if options.values.per_target_caching:
        results = await MultiGet(
            Get[LintResult](LinterConfigurations, config_collection.__class__([config]))
            for config_collection in valid_config_collections
            for config in config_collection
        )
    else:
        results = await MultiGet(
            Get[LintResult](LinterConfigurations, config_collection)
            for config_collection in valid_config_collections
        )

    if not results:
        return Lint(exit_code=0)

    exit_code = 0
    for result in results:
        if result.stdout:
            console.print_stdout(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)
        if result.exit_code != 0:
            exit_code = result.exit_code

    return Lint(exit_code)


def rules():
    return [lint]
