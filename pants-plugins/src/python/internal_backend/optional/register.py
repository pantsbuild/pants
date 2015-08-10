# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.backend.jvm.tasks.scalastyle import Scalastyle
from pants.backend.python.tasks.checkstyle.class_factoring import ClassFactoringCheck
from pants.backend.python.tasks.checkstyle.except_statements import ExceptStatementsCheck
from pants.backend.python.tasks.checkstyle.future_compatibility import FutureCompatibilityCheck
from pants.backend.python.tasks.checkstyle.import_order import ImportOrderCheck
from pants.backend.python.tasks.checkstyle.indentation import IndentationCheck
from pants.backend.python.tasks.checkstyle.missing_contextmanager import MissingContextManagerCheck
from pants.backend.python.tasks.checkstyle.new_style_classes import NewStyleClassesCheck
from pants.backend.python.tasks.checkstyle.newlines import NewlinesCheck
from pants.backend.python.tasks.checkstyle.pep8 import PEP8Check
from pants.backend.python.tasks.checkstyle.print_statements import PrintStatementsCheck
from pants.backend.python.tasks.checkstyle.pyflakes import FlakeCheck
from pants.backend.python.tasks.checkstyle.trailing_whitespace import TrailingWhitespaceCheck
from pants.backend.python.tasks.checkstyle.variable_names import VariableNamesCheck
from pants.backend.python.tasks.python_eval import PythonEval
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='python-eval', action=PythonEval).install('compile')
  task(name='checkstyle', action=Checkstyle).install('compile')
  task(name='scalastyle', action=Scalastyle).install('compile')

  task(name='style-class-factoring', action=ClassFactoringCheck).install('compile')
  task(name='except-statement', action=ExceptStatementsCheck).install('compile')
  task(name='future-compatibility', action=FutureCompatibilityCheck).install('compile')
  task(name='import-order', action=ImportOrderCheck).install('compile')
  task(name='indentation', action=IndentationCheck).install('compile')
  task(name='missing-context-manager', action=MissingContextManagerCheck).install('compile')
  task(name='new-style-classes', action=NewStyleClassesCheck).install('compile')
  task(name='newlines', action=NewlinesCheck).install('compile')
  task(name='pep8', action=PEP8Check).install('compile')
  task(name='print-statements', action=PrintStatementsCheck).install('compile')
  task(name='pyflakes', action=FlakeCheck).install('compile')
  task(name='trailing-whitespace', action=TrailingWhitespaceCheck).install('compile')
  task(name='variable-names', action=VariableNamesCheck).install('compile')
