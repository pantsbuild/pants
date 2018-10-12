# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.contrib.python.checks.checker.pyflakes import PyflakesChecker
from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


class FlakeCheckSubsystem(PluginSubsystemBase):
  options_scope = 'pycheck-pyflakes'

  @classmethod
  def register_options(cls, register):
    super(FlakeCheckSubsystem, cls).register_options(register)
    register('--ignore', fingerprint=True, type=list, default=[],
             help='List of warning codes to ignore.')

  @classmethod
  def plugin_type(cls):
    return PyflakesChecker
