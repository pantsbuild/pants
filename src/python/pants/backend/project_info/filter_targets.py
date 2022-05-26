# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from enum import Enum
from typing import Pattern

from pants.base.deprecated import warn_or_error
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import RegisteredTargetTypes, Tags, Target, UnrecognizedTargetTypeException
from pants.option.option_types import EnumOption, StrListOption
from pants.util.docutil import bin_name
from pants.util.enums import match
from pants.util.filtering import TargetFilter, and_filters, create_filters
from pants.util.memo import memoized
from pants.util.strutil import softwrap


class TargetGranularity(Enum):
    all_targets = "all"
    file_targets = "file"
    build_targets = "BUILD"


class FilterSubsystem(LineOriented, GoalSubsystem):
    name = "filter"
    help = softwrap(
        """
        Filter the input targets based on various criteria.

        Most of the filtering options below are comma-separated lists of filtering criteria, with
        an implied logical OR between them, so that a target passes the filter if it matches any of
        the criteria in the list. A '-' prefix inverts the sense of the entire comma-separated list,
        so that a target passes the filter only if it matches none of the criteria in the list.

        Each of the filtering options may be specified multiple times, with an implied logical AND
        between them.
        """
    )

    target_type = StrListOption(
        "--target-type",
        metavar="[+-]type1,type2,...",
        help="Filter on these target types, e.g. `resources` or `python_sources`.",
    )
    granularity = EnumOption(
        "--granularity",
        default=TargetGranularity.all_targets,
        help=softwrap(
            """
            Filter to rendering only targets declared in BUILD files, only file-level
            targets, or all targets.
            """
        ),
    )
    address_regex = StrListOption(
        "--address-regex",
        metavar="[+-]regex1,regex2,...",
        help="Filter on target addresses matching these regexes.",
    )
    tag_regex = StrListOption(
        "--tag-regex",
        metavar="[+-]regex1,regex2,...",
        help="Filter on targets with tags matching these regexes.",
    )

    def target_type_filters(
        self, registered_target_types: RegisteredTargetTypes
    ) -> list[TargetFilter]:
        def outer_filter(target_alias: str) -> TargetFilter:
            if target_alias not in registered_target_types.aliases:
                raise UnrecognizedTargetTypeException(target_alias, registered_target_types)

            target_type = registered_target_types.aliases_to_types[target_alias]
            if target_type.deprecated_alias and target_alias == target_type.deprecated_alias:
                warn_deprecated_target_type(target_type)

            def inner_filter(tgt: Target) -> bool:
                return tgt.alias == target_alias or bool(
                    tgt.deprecated_alias and tgt.deprecated_alias == target_alias
                )

            return inner_filter

        return create_filters(self.target_type, outer_filter)

    def address_regex_filters(self) -> list[TargetFilter]:
        def outer_filter(address_regex: str) -> TargetFilter:
            regex = compile_regex(address_regex)
            return lambda tgt: bool(regex.search(tgt.address.spec))

        return create_filters(self.address_regex, outer_filter)

    def tag_regex_filters(self) -> list[TargetFilter]:
        def outer_filter(tag_regex: str) -> TargetFilter:
            regex = compile_regex(tag_regex)
            return lambda tgt: any(bool(regex.search(tag)) for tag in tgt.get(Tags).value or ())

        return create_filters(self.tag_regex, outer_filter)

    def granularity_filter(self) -> TargetFilter:
        return match(
            self.granularity,
            {
                TargetGranularity.all_targets: lambda _: True,
                TargetGranularity.file_targets: lambda tgt: tgt.address.is_file_target,
                TargetGranularity.build_targets: lambda tgt: not tgt.address.is_file_target,
            },
        )

    def all_filters(self, registered_target_types: RegisteredTargetTypes) -> TargetFilter:
        return and_filters(
            [
                *self.target_type_filters(registered_target_types),
                *self.address_regex_filters(),
                *self.tag_regex_filters(),
                self.granularity_filter(),
            ]
        )

    def is_specified(self) -> bool:
        """Return true if any of the options are set."""
        return bool(self.target_type or self.address_regex or self.tag_regex or self.granularity)


class FilterGoal(Goal):
    subsystem_cls = FilterSubsystem


def compile_regex(regex: str) -> Pattern:
    try:
        return re.compile(regex)
    except re.error as e:
        raise re.error(f"Invalid regular expression {repr(regex)}: {e}")


# Memoized so the deprecation doesn't happen repeatedly.
@memoized
def warn_deprecated_target_type(tgt_type: type[Target]) -> None:
    assert tgt_type.deprecated_alias_removal_version is not None
    warn_or_error(
        removal_version=tgt_type.deprecated_alias_removal_version,
        entity=f"using `--filter-target-type={tgt_type.deprecated_alias}`",
        hint=f"Use `--filter-target-type={tgt_type.alias}` instead.",
    )


@goal_rule
def filter_targets(
    addresses: Addresses, filter_subsystem: FilterSubsystem, console: Console
) -> FilterGoal:
    warn_or_error(
        "2.14.0.dev0",
        "using `filter` as a goal",
        softwrap(
            f"""
            You can now specify `filter` arguments with any goal, e.g. `{bin_name()}
            --filter-target-type=python_test test ::`.

            This means that the `filter` goal is now identical to `list`. For example, rather than
            `{bin_name()} filter --target-type=python_test ::`, use
            `{bin_name()} --filter-target-type=python_test list ::`.

            Often, the `filter` goal was combined with `xargs` to build pipelines of commands. You
            can often now simplify those to a single command. Rather than `{bin_name()} filter
            --target-type=python_test filter :: | xargs {bin_name()} test`, simply use
            `{bin_name()} --filter-target-type=python_test test ::`.
            """
        ),
    )
    # `SpecsFilter` will have already filtered for us. There isn't much reason for this goal to
    # exist anymore.
    with filter_subsystem.line_oriented(console) as print_stdout:
        for address in sorted(addresses):
            print_stdout(address.spec)
    return FilterGoal(exit_code=0)


def rules():
    return collect_rules()
