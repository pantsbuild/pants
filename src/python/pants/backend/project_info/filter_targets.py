# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from functools import partial
from typing import Callable, Pattern

from pants.base.deprecated import resolve_conflicting_options
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
from pants.util.filtering import and_filters, create_filters

TARGET_REMOVAL_MSG = (
    "`--filter-target` was removed because it is similar to `--filter-address-regex`. If you still "
    "need this feature, please message us on Slack (https://www.pantsbuild.org/docs/community)."
)
ANCESTOR_REMOVAL_MSG = (
    "`--filter-ancestor` was removed because it is not trivial to implement. If you still need "
    "this feature, please message us on Slack (https://www.pantsbuild.org/docs/community)."
)


class FilterSubsystem(LineOriented, GoalSubsystem):
    """Filter the input targets based on various criteria.

    Each of the filtering options below is a comma-separated list of filtering criteria, with an
    implied logical OR between them, so that a target passes the filter if it matches any of the
    criteria in the list.  A '-' prefix inverts the sense of the entire comma-separated list, so
    that a target passes the filter only if it matches none of the criteria in the list.

    Each of the filtering options may be specified multiple times, with an implied logical AND
    between them.
    """

    name = "filter"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--target-type",
            type=list,
            metavar="[+-]type1,type2,...",
            help="Filter on these target types, e.g. `resources` or `python_library`.",
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
        register(
            "--type",
            type=list,
            metavar="[+-]type1,type2,...",
            help="Filter on these target types, e.g. `resources` or `python_library`.",
            removal_version="2.1.0.dev0",
            removal_hint="Use `--target-type` instead of `--type`.",
        )
        register(
            "--regex",
            type=list,
            metavar="[+-]regex1,regex2,...",
            help="Filter on target addresses matching these regexes.",
            removal_version="2.1.0.dev0",
            removal_hint="Use `--address-regex` instead of `--regex`.",
        )
        register(
            "--target",
            type=list,
            metavar="[+-]spec1,spec2,...",
            help="Filter on these target addresses.",
            removal_version="2.1.0.dev0",
            removal_hint=TARGET_REMOVAL_MSG,
        )
        register(
            "--ancestor",
            type=list,
            metavar="[+-]spec1,spec2,...",
            help="Filter on targets that these targets depend on.",
            removal_version="2.1.0.dev0",
            removal_hint=ANCESTOR_REMOVAL_MSG,
        )


class FilterGoal(Goal):
    subsystem_cls = FilterSubsystem


def compile_regex(regex: str) -> Pattern:
    try:
        return re.compile(regex)
    except re.error as e:
        raise re.error(f"Invalid regular expression {repr(regex)}: {e}")


TargetFilter = Callable[[Target], bool]


@goal_rule
def filter_targets(
    targets: UnexpandedTargets,
    filter_subsystem: FilterSubsystem,
    console: Console,
    registered_target_types: RegisteredTargetTypes,
) -> FilterGoal:
    if not filter_subsystem.options.is_default("target"):
        raise ValueError(TARGET_REMOVAL_MSG)
    if not filter_subsystem.options.is_default("ancestor"):
        raise ValueError(ANCESTOR_REMOVAL_MSG)

    def filter_target_type(target_type: str) -> TargetFilter:
        if target_type not in registered_target_types.aliases:
            raise UnrecognizedTargetTypeException(target_type, registered_target_types)
        return lambda tgt: tgt.alias == target_type

    def filter_address_regex(address_regex: str) -> TargetFilter:
        regex = compile_regex(address_regex)
        return lambda tgt: bool(regex.search(tgt.address.spec))

    def filter_tag_regex(tag_regex: str) -> TargetFilter:
        regex = compile_regex(tag_regex)
        return lambda tgt: any(bool(regex.search(tag)) for tag in tgt.get(Tags).value or ())

    resolve_option = partial(
        resolve_conflicting_options,
        old_scope="filter",
        new_scope="filter",
        old_container=filter_subsystem.options,
        new_container=filter_subsystem.options,
    )
    target_type = resolve_option(old_option="type", new_option="target_type")
    address_regex = resolve_option(old_option="regex", new_option="address_regex")

    anded_filter: TargetFilter = and_filters(
        [
            *(create_filters(target_type, filter_target_type)),
            *(create_filters(address_regex, filter_address_regex)),
            *(create_filters(filter_subsystem.options.tag_regex, filter_tag_regex)),
        ]
    )
    addresses = sorted(target.address for target in targets if anded_filter(target))

    with filter_subsystem.line_oriented(console) as print_stdout:
        for address in addresses:
            print_stdout(address.spec)
    return FilterGoal(exit_code=0)


def rules():
    return collect_rules()
