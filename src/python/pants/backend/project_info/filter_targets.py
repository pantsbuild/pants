# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from enum import Enum
from typing import Callable, Pattern

from pants.base.deprecated import warn_or_error
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import (
    RegisteredTargetTypes,
    Tags,
    Target,
    UnexpandedTargets,
    UnrecognizedTargetTypeException,
)
from pants.util.enums import match
from pants.util.filtering import and_filters, create_filters
from pants.util.memo import memoized


class TargetGranularity(Enum):
    all_targets = "all"
    file_targets = "file"
    build_targets = "BUILD"


class FilterSubsystem(LineOriented, GoalSubsystem):
    name = "filter"
    help = (
        "Filter the input targets based on various criteria.\n\nMost of the filtering options "
        "below are comma-separated lists of filtering criteria, with an implied logical OR between "
        "them, so that a target passes the filter if it matches any of the criteria in the list. "
        "A '-' prefix inverts the sense of the entire comma-separated list, so that a target "
        "passes the filter only if it matches none of the criteria in the list.\n\nEach of the "
        "filtering options may be specified multiple times, with an implied logical AND between "
        "them."
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--target-type",
            type=list,
            metavar="[+-]type1,type2,...",
            help="Filter on these target types, e.g. `resources` or `python_sources`.",
        )
        register(
            "--granularity",
            type=TargetGranularity,
            default=TargetGranularity.all_targets,
            help=(
                "Filter to rendering only targets declared in BUILD files, only file-level "
                "targets, or all targets."
            ),
        )
        register(
            "--address-regex",
            type=list,
            metavar="[+-]regex1,regex2,...",
            help="Filter on target addresses matching these regexes.",
        )
        register(
            "--tag-regex",
            type=list,
            metavar="[+-]regex1,regex2,...",
            help="Filter on targets with tags matching these regexes.",
        )


class FilterGoal(Goal):
    subsystem_cls = FilterSubsystem


def compile_regex(regex: str) -> Pattern:
    try:
        return re.compile(regex)
    except re.error as e:
        raise re.error(f"Invalid regular expression {repr(regex)}: {e}")


TargetFilter = Callable[[Target], bool]


# Memoized so the deprecation doesn't happen repeatedly.
@memoized
def warn_deprecated_target_type(tgt_type: type[Target]) -> None:
    assert tgt_type.deprecated_alias_removal_version is not None
    warn_or_error(
        removal_version=tgt_type.deprecated_alias_removal_version,
        entity=f"using `filter --target-type={tgt_type.deprecated_alias}`",
        hint=f"Use `filter --target-type={tgt_type.alias}` instead.",
    )


@goal_rule
def filter_targets(
    # NB: We must preserve target generators, not replace with their generated targets.
    targets: UnexpandedTargets,
    filter_subsystem: FilterSubsystem,
    console: Console,
    registered_target_types: RegisteredTargetTypes,
) -> FilterGoal:
    def filter_target_type(target_type: str) -> TargetFilter:
        if target_type not in registered_target_types.aliases:
            raise UnrecognizedTargetTypeException(target_type, registered_target_types)

        def filt(tgt: Target) -> bool:
            if tgt.alias == target_type:
                return True
            if tgt.deprecated_alias == target_type:
                warn_deprecated_target_type(type(tgt))
                return True
            return False

        return filt

    def filter_address_regex(address_regex: str) -> TargetFilter:
        regex = compile_regex(address_regex)
        return lambda tgt: bool(regex.search(tgt.address.spec))

    def filter_tag_regex(tag_regex: str) -> TargetFilter:
        regex = compile_regex(tag_regex)
        return lambda tgt: any(bool(regex.search(tag)) for tag in tgt.get(Tags).value or ())

    def filter_granularity(granularity: TargetGranularity) -> TargetFilter:
        return match(
            granularity,
            {
                TargetGranularity.all_targets: lambda _: True,
                TargetGranularity.file_targets: lambda tgt: tgt.address.is_file_target,
                TargetGranularity.build_targets: lambda tgt: not tgt.address.is_file_target,
            },
        )

    anded_filter: TargetFilter = and_filters(
        [
            *(create_filters(filter_subsystem.options.target_type, filter_target_type)),
            *(create_filters(filter_subsystem.options.address_regex, filter_address_regex)),
            *(create_filters(filter_subsystem.options.tag_regex, filter_tag_regex)),
            filter_granularity(filter_subsystem.options.granularity),
        ]
    )
    addresses = sorted(target.address for target in targets if anded_filter(target))

    with filter_subsystem.line_oriented(console) as print_stdout:
        for address in addresses:
            print_stdout(address.spec)
    return FilterGoal(exit_code=0)


def rules():
    return collect_rules()
