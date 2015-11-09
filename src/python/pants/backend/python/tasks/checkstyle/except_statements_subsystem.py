# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


class ExceptStatementsSubsystem(PluginSubsystemBase):
  options_scope = 'pycheck-except-statement'

  def get_plugin_type(self):
    from pants.backend.python.tasks.checkstyle.except_statements import ExceptStatements
    return ExceptStatements
