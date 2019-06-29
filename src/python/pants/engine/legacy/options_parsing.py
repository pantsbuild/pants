# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import RootRule, rule
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import Scope, ScopedOptions
from pants.util.objects import datatype


class _Options(datatype([('options', Options)])):
  """A wrapper around bootstrapped options values: not for direct consumption."""


@rule(_Options, [OptionsBootstrapper])
def parse_options(options_bootstrapper):
  # TODO: Because _OptionsBootstapper is currently provided as a Param, this @rule relies on options
  # remaining relatively stable in order to be efficient. See #6845 for a discussion of how to make
  # minimize the size of that value.
  build_config = BuildConfigInitializer.get(options_bootstrapper)
  return _Options(OptionsInitializer.create(options_bootstrapper, build_config, init_subsystems=False))


@rule(ScopedOptions, [Scope, _Options])
def scope_options(scope, options):
  return ScopedOptions(scope, options.options.for_scope(scope.scope))


def create_options_parsing_rules():
  return [
    scope_options,
    parse_options,
    RootRule(Scope),
    RootRule(OptionsBootstrapper),
  ]
