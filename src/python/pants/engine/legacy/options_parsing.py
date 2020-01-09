# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.rules import RootRule, rule
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.global_options import GlobalOptions
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import Scope, ScopedOptions


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
  return _Options(OptionsInitializer.create(options_bootstrapper, build_config, init_subsystems=False))


@rule
def scope_options(scope: Scope, options: _Options) -> ScopedOptions:
  return ScopedOptions(scope, options.options.for_scope(scope.scope))


@rule
def global_options(options_bootstrapper: OptionsBootstrapper) -> GlobalOptions:
  global_options = options_bootstrapper.bootstrap_options.for_global_scope()
  return GlobalOptions(_inner=global_options)


def create_options_parsing_rules():
  return [
    scope_options,
    parse_options,
    global_options,
    RootRule(Scope),
    RootRule(OptionsBootstrapper),
  ]
