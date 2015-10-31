# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.class_factoring_subsystem import ClassFactoringSubsystem
from pants.backend.python.tasks.checkstyle.except_statements_subsystem import \
  ExceptStatementsSubsystem
from pants.backend.python.tasks.checkstyle.future_compatibility_subsystem import \
  FutureCompatibilitySubsystem
from pants.backend.python.tasks.checkstyle.import_order_subsystem import ImportOrderSubsystem
from pants.backend.python.tasks.checkstyle.indentation_subsystem import IndentationSubsystem
from pants.backend.python.tasks.checkstyle.missing_contextmanager_subsystem import \
  MissingContextManagerSubsystem
from pants.backend.python.tasks.checkstyle.new_style_classes_subsystem import \
  NewStyleClassesSubsystem
from pants.backend.python.tasks.checkstyle.newlines_subsystem import NewlinesSubsystem
from pants.backend.python.tasks.checkstyle.pep8_subsystem import PEP8Subsystem
from pants.backend.python.tasks.checkstyle.print_statements_subsystem import \
  PrintStatementsSubsystem
from pants.backend.python.tasks.checkstyle.pyflakes_subsystem import FlakeCheckSubsystem
from pants.backend.python.tasks.checkstyle.trailing_whitespace_subsystem import \
  TrailingWhitespaceSubsystem
from pants.backend.python.tasks.checkstyle.variable_names_subsystem import VariableNamesSubsystem


def register_plugins(task):
  task.register_plugin('class-factoring', ClassFactoringSubsystem)
  task.register_plugin('except-statement', ExceptStatementsSubsystem)
  task.register_plugin('future-compatibility', FutureCompatibilitySubsystem)
  task.register_plugin('import-order', ImportOrderSubsystem)
  task.register_plugin('indentation', IndentationSubsystem)
  task.register_plugin('missing-context-manager', MissingContextManagerSubsystem)
  task.register_plugin('new-style-classes', NewStyleClassesSubsystem)
  task.register_plugin('newlines', NewlinesSubsystem)
  task.register_plugin('print-statements', PrintStatementsSubsystem)
  task.register_plugin('pyflakes', FlakeCheckSubsystem)
  task.register_plugin('trailing-whitespace', TrailingWhitespaceSubsystem)
  task.register_plugin('variable-names', VariableNamesSubsystem)
  task.register_plugin('pep8', PEP8Subsystem)
