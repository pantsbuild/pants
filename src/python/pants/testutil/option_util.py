# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable, Mapping, TypeVar

from pants.engine.goal import GoalSubsystem
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.ranked_value import Rank, RankedValue, Value
from pants.option.subsystem import Subsystem


def create_options_bootstrapper(
    args: Iterable[str] | None = None, *, env: Mapping[str, str] | None = None
) -> OptionsBootstrapper:
    return OptionsBootstrapper.create(
        args=("pants", "--pants-config-files=[]", *(args or [])),
        env=env or {},
        allow_pantsrc=False,
    )


def create_option_value_container(
    default_rank: Rank = Rank.NONE, **options: RankedValue | Value
) -> OptionValueContainer:
    scoped_options = OptionValueContainerBuilder()
    for key, value in options.items():
        if not isinstance(value, RankedValue):
            value = RankedValue(default_rank, value)
        setattr(scoped_options, key, value)
    return scoped_options.build()


_GS = TypeVar("_GS", bound=GoalSubsystem)


def create_goal_subsystem(
    goal_subsystem_type: type[_GS],
    default_rank: Rank = Rank.NONE,
    **options: RankedValue | Value,
) -> _GS:
    """Creates a new goal subsystem instance populated with the given option values.

    :param goal_subsystem_type: The `GoalSubsystem` type to create.
    :param default_rank: The rank to assign any raw option values passed.
    :param options: The option values to populate the new goal subsystem instance with.
    """
    return goal_subsystem_type(
        options=create_option_value_container(default_rank, **options),
    )


_SS = TypeVar("_SS", bound=Subsystem)


def create_subsystem(
    subsystem_type: type[_SS], default_rank: Rank = Rank.NONE, **options: RankedValue | Value
) -> _SS:
    """Creates a new subsystem instance populated with the given option values.

    :param subsystem_type: The `Subsystem` type to create.
    :param default_rank: The rank to assign any raw option values passed.
    :param options: The option values to populate the new subsystem instance with.
    """
    return subsystem_type(
        options=create_option_value_container(default_rank, **options),
    )
