# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.rules import RootRule, rule, subsystem_rule
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.global_options import GlobalOptions
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import Scope, ScopedOptions
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class _Options:
    """A wrapper around bootstrapped options values: not for direct consumption."""

    options: Options


@rule
def parse_options(options_bootstrapper: OptionsBootstrapper) -> _Options:
    # TODO: Because _OptionsBootstapper is currently provided as a Param, this @rule relies on options
    # remaining relatively stable in order to be efficient. See #6845 for a discussion of how to make
    # minimize the size of that value.
    build_config = BuildConfigInitializer.get(options_bootstrapper)
    return _Options(
        OptionsInitializer.create(options_bootstrapper, build_config, init_subsystems=False)
    )


@rule
def scope_options(scope: Scope, options: _Options) -> ScopedOptions:
    return ScopedOptions(scope, options.options.for_scope(scope.scope))


@rule
def log_level(global_options: GlobalOptions) -> LogLevel:
    log_level: LogLevel = global_options.get_options().level
    return log_level


def create_options_parsing_rules():
    return [
        scope_options,
        parse_options,
        subsystem_rule(GlobalOptions),
        log_level,
        RootRule(Scope),
        RootRule(OptionsBootstrapper),
    ]
