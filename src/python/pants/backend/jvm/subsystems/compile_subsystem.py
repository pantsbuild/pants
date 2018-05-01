# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class JvmCompileSubsystem(Subsystem):
  """Used to keep track of global jvm compiler option

  :API: public
  """
  options_scope = 'compiler'

  @classmethod
  def register_options(cls, register):
    super(JvmCompileSubsystem, cls).register_options(register)
    register('--compiler', choices=['zinc', 'javac'], default='zinc', help='Java compiler implementation to use.')
