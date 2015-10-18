# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task


class JmakeCompile(Task):
  """Compile Java code using JMake."""

  @classmethod
  def register_options(cls, register):
    super(JmakeCompile, cls).register_options(register)
    register('--use-jmake', advanced=True, action='store_true', default=False,
             deprecated_version='0.0.59',
             deprecated_hint='jmake is no longer supported, and this option has no effect.',
             fingerprint=True,
             help='Use jmake to compile Java targets')

  def execute(self):
    """This task is a noop to hold the option mentioned above."""
    pass
