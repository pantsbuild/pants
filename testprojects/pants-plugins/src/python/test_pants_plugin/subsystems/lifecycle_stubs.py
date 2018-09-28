# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class LifecycleStubs(Subsystem):
  options_scope = 'lifecycle-stubs'

  @classmethod
  def register_options(cls, register):
    super(LifecycleStubs, cls).register_options(register)
    register('--add-exiter-message', type=str, default=None,
             help='Add a message which displays to stderr on fatal exit.')

  @memoized_property
  def add_exiter_message(self):
    return self.get_options().add_exiter_message
