# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem


class GoPlatform(Subsystem):

  options_scope = 'go-platform'

  @classmethod
  def register_options(cls, register):
    super(GoPlatform, cls).register_options(register)
    register('--remote-pkg-root',
             help='Directory where remote Go packages are rooted.')

  @property
  def remote_pkg_root(self):
    return self.get_options().remote_pkg_root
