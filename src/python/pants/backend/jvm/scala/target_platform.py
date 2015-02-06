# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.config import Config


# TODO(John Sirois): Rework the config here - this is a stop-gap.  At a minimum  TargetPlatform
# should not be depending on a scala-compile keys.  There should also be a more disciplined notion
# of target platform version from which default deps could be derived.  A technical hurdle is that
# the currency is dep specs today which forces emitting a BUILD file containing the default spec
# pointee targets to achieve true works-from-default operation.


class TargetPlatform(object):
  """Encapsulates information about the configured default scala target platform."""

  def __init__(self, config=None):
    self._config = config or Config.from_cache()

  @property
  def default_compiler_specs(self):
    """Returns a list of target specs pointing to the default scalac tool libraries.

    The tool libraries are set in option scalac in scope compile.scala, currently registered
    in ZincUtils.register_options().
    """
    return ['//:scala-compiler']

  @property
  def library_specs(self):
    """Returns a list of target specs pointing to the scala runtime libraries.

    TODO: Convert this to an option, once we figure out how to plumb options through.
    """
    return self._config.getlist('compile.scala', 'runtime-deps',
                                default=['//:scala-library'])
