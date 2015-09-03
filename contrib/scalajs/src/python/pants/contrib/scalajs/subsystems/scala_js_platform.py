# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.custom_types import target_list_option
from pants.subsystem.subsystem import Subsystem


class ScalaJSPlatform(Subsystem):
  """The scala js platform."""

  options_scope = 'scala-js-platform'

  @classmethod
  def register_options(cls, register):
    super(ScalaJSPlatform, cls).register_options(register)
    register('--runtime', advanced=True, type=target_list_option, default=['//:scala-js-library'],
             help='Target specs pointing to the scala-js runtime libraries.')

  @property
  def runtime(self):
    return self.get_options().runtime
