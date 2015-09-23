# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.class_factoring import ClassFactoring
from pants.backend.python.tasks.checkstyle.except_statements import ExceptStatements
from pants.backend.python.tasks.checkstyle.future_compatibility import FutureCompatibility
from pants.backend.python.tasks.checkstyle.import_order import ImportOrder
from pants.backend.python.tasks.checkstyle.indentation import Indentation
from pants.backend.python.tasks.checkstyle.missing_contextmanager import MissingContextManager
from pants.backend.python.tasks.checkstyle.new_style_classes import NewStyleClasses
from pants.backend.python.tasks.checkstyle.newlines import Newlines
from pants.backend.python.tasks.checkstyle.pep8 import PEP8Checker
from pants.backend.python.tasks.checkstyle.print_statements import PrintStatements
from pants.backend.python.tasks.checkstyle.pyflakes import PyflakesChecker
from pants.backend.python.tasks.checkstyle.trailing_whitespace import TrailingWhitespace
from pants.backend.python.tasks.checkstyle.variable_names import PEP8VariableNames


def register_plugins(task):
  task.register_plugin(name='class-factoring', checker=ClassFactoring)
  task.register_plugin(name='except-statement', checker=ExceptStatements)
  task.register_plugin(name='future-compatibility', checker=FutureCompatibility)
  task.register_plugin(name='import-order', checker=ImportOrder)
  task.register_plugin(name='indentation', checker=Indentation)
  task.register_plugin(name='missing-context-manager', checker=MissingContextManager)
  task.register_plugin(name='new-style-classes', checker=NewStyleClasses)
  task.register_plugin(name='newlines', checker=Newlines)
  task.register_plugin(name='print-statements', checker=PrintStatements)
  task.register_plugin(name='pyflakes', checker=PyflakesChecker)
  task.register_plugin(name='trailing-whitespace', checker=TrailingWhitespace)
  task.register_plugin(name='variable-names', checker=PEP8VariableNames)
  task.register_plugin(name='pep8', checker=PEP8Checker)
