# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class JvmResolveSubsystem(Subsystem):
  """A JVM invocation.

  :API: public
  """
  options_scope = 'resolver'

  @classmethod
  def register_options(cls, register):
    super(JvmResolveSubsystem, cls).register_options(register)
    # TODO(benjy): Options to specify the JVM version?
    register('--resolver', choices=['ivy', 'coursier'], default='ivy', help='Pick a resolver.')
