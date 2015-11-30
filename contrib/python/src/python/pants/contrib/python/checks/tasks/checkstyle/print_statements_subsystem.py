# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


class PrintStatementsSubsystem(PluginSubsystemBase):
  options_scope = 'pycheck-print-statements'

  def get_plugin_type(self):
    from pants.contrib.python.checks.tasks.checkstyle.print_statements import PrintStatements
    return PrintStatements
