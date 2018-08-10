# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.objects import datatype


class OptionsParseRequest(datatype(['args', 'env'])):
  """Represents a request for Options computation."""

  @classmethod
  def create(cls, args, env):
    assert isinstance(args, (list, tuple))
    return cls(
      tuple(args),
      tuple(sorted(env.items() if isinstance(env, dict) else env))
    )


class Options(datatype(['options', 'build_config'])):
  """Represents the result of an Options computation."""


# TODO: Accommodate file_option, dir_option, etc.
@rule(Options, [Select(OptionsBootstrapper), Select(BuildConfiguration)])
def parse_options(options_bootstrapper, build_config):
  options = OptionsInitializer.create(options_bootstrapper, build_config)
  options.freeze()
  return Options(options, build_config)


def create_options_parsing_rules():
  return [
    parse_options,
    RootRule(OptionsBootstrapper),
  ]
