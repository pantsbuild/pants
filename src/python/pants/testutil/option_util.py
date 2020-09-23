# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, Mapping, Optional, Type, TypeVar, Union, cast

from pants.engine.goal import GoalSubsystem
from pants.option.option_value_container import OptionValueContainer, OptionValueContainerBuilder
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.ranked_value import Rank, RankedValue, Value
from pants.option.subsystem import Subsystem


def create_options_bootstrapper(
    *,
    args: Optional[Iterable[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> OptionsBootstrapper:
    return OptionsBootstrapper.create(
        args=("--pants-config-files=[]", *(args or [])),
        env=env or {},
        allow_pantsrc=False,
    )


def _create_scoped_options(
    default_rank: Rank, **options: Union[RankedValue, Value]
) -> OptionValueContainer:
    scoped_options = OptionValueContainerBuilder()
    for key, value in options.items():
        if not isinstance(value, RankedValue):
            value = RankedValue(default_rank, value)
        setattr(scoped_options, key, value)
    return scoped_options.build()


_GS = TypeVar("_GS", bound=GoalSubsystem)


def create_goal_subsystem(
    goal_subsystem_type: Type[_GS],
    default_rank: Rank = Rank.NONE,
    **options: Union[RankedValue, Value],
) -> _GS:
    """Creates a new goal subsystem instance populated with the given option values.

    :param goal_subsystem_type: The `GoalSubsystem` type to create.
    :param default_rank: The rank to assign any raw option values passed.
    :param options: The option values to populate the new goal subsystem instance with.
    """
    return goal_subsystem_type(
        scope=goal_subsystem_type.name,
        options=_create_scoped_options(default_rank, **options),
    )


_SS = TypeVar("_SS", bound=Subsystem)


def create_subsystem(
    subsystem_type: Type[_SS], default_rank: Rank = Rank.NONE, **options: Union[RankedValue, Value]
) -> _SS:
    """Creates a new subsystem instance populated with the given option values.

    :param subsystem_type: The `Subsystem` type to create.
    :param default_rank: The rank to assign any raw option values passed.
    :param options: The option values to populate the new subsystem instance with.
    """
    options_scope = cast(str, subsystem_type.options_scope)
    return subsystem_type(
        scope=options_scope,
        options=_create_scoped_options(default_rank, **options),
    )
