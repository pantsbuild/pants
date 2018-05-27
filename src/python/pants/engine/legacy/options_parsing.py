# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.fs import FileContent, PathGlobs
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.objects import datatype


class OptionsParseRequest(datatype(['args', 'env'])):
  """Represents a request for Options computation."""

  @classmethod
  def create(cls, args, env):
    assert isinstance(args, (list, tuple))
    return cls(
      tuple(args),
      tuple(env.items() if isinstance(env, dict) else env)
    )


class Options(datatype(['options', 'build_config'])):
  """Represents the result of an Options computation."""


@rule(OptionsBootstrapper, [Select(OptionsParseRequest)])
def reify_options_bootstrapper(parse_request):
  options_bootstrapper = OptionsBootstrapper(
    env=dict(parse_request.env),
    args=parse_request.args
  )
  # TODO: Once we have the ability to get FileContent for arbitrary
  # paths outside of the buildroot, we can invert this to use
  # OptionsBootstrapper.produce_and_set_bootstrap_options() which
  # will yield lists of file paths for use as subject values and permit
  # us to avoid the direct file I/O that this rule currently requires.
  options_bootstrapper.construct_and_set_bootstrap_options()
  yield options_bootstrapper


# TODO: Accommodate file_option, dir_option, etc.
@rule(Options, [Select(OptionsBootstrapper), Select(BuildConfiguration)])
def parse_options(options_bootstrapper, build_config):
  options = OptionsInitializer.create(options_bootstrapper, build_config)
  options.freeze()
  return Options(options, build_config)


def create_options_parsing_rules():
  return [
    reify_options_bootstrapper,
    parse_options,
    RootRule(OptionsParseRequest),
  ]
