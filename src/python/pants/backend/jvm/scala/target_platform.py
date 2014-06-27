# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.config import Config


# TODO(John Sirois): Rework the config here - this is a stop-gap.  At a minimum  TargetPlatform
# should not be depending on a scala-compile keys.  There should also be a more disciplined notion
# of target platform version from which default deps could be derived.  A technical hurdle is that
# the currency is dep specs today which forces emitting a BUILD file containing the default spec
# pointee targets to achieve true works-from-default operation.


class TargetPlatform(object):
  """Encapsulates information about the configured default scala target platform."""

  def __init__(self, config=None):
    self._config = config or Config.load()

  @property
  def compiler_specs(self):
    """Returns a list of target specs pointing to the scalac tool libraries."""
    return self._config.getlist('scala-compile', 'compile-bootstrap-tools',
                                default=['//:scala-compiler-2.9.3'])

  @property
  def library_specs(self):
    """Returns a list of target specs pointing to the scala runtime libraries."""
    return self._config.getlist('scala-compile', 'runtime-deps',
                                default=['//:scala-library-2.9.3'])
