# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.internals.session import SessionValues
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import OptionsParsingSettings, Scope, ScopedOptions
from pants.util.memo import memoized_property


@dataclass(frozen=True)
class _Options:
    """A wrapper around bootstrapped options values: not for direct consumption.

    TODO: This odd indirection exists because the `Options` type does not have useful `eq`, but
    OptionsBootstrapper and BuildConfiguration both do.
    """

    options_bootstrapper: OptionsBootstrapper
    options_parsing_settings: OptionsParsingSettings
    union_membership: UnionMembership

    def __post_init__(self) -> None:
        # Touch the options property to ensure that it is eagerly initialized at construction time,
        # rather than potentially much later in the presence of concurrency.
        assert self.options is not None

    @memoized_property
    def options(self) -> Options:
        return self.options_bootstrapper.full_options(
            self.options_parsing_settings.known_scope_infos,
            self.union_membership,
            self.options_parsing_settings.allow_unknown_options,
        )


@rule
async def parse_options(
    options_parsing_settings: OptionsParsingSettings,
    session_values: SessionValues,
    union_membership: UnionMembership,
) -> _Options:
    # TODO: Once the OptionsBootstrapper has been removed from all relevant QueryRules, this lookup
    # should be extracted into a separate @rule.
    options_bootstrapper = session_values[OptionsBootstrapper]
    return _Options(options_bootstrapper, options_parsing_settings, union_membership)


@rule
async def scope_options(scope: Scope, options: _Options) -> ScopedOptions:
    return ScopedOptions(scope, options.options.for_scope(scope.scope))


def rules():
    return collect_rules()
