# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.subsystem.subsystem import Subsystem
from pants.util.objects import enum


class JvmResolveSubsystem(Subsystem):
  """Used to keep track of global jvm resolver settings

  :API: public
  """
  options_scope = 'resolver'

  class ResolverChoices(enum(['ivy', 'coursier'])): pass

  @classmethod
  def register_options(cls, register):
    super(JvmResolveSubsystem, cls).register_options(register)
    register('--resolver', type=cls.ResolverChoices, default=cls.ResolverChoices.ivy,
             help='Resolver to use for external jvm dependencies.')
