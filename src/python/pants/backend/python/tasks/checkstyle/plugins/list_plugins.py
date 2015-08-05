# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.class_factoring import ClassFactoring
from pants.backend.python.tasks.except_statements import ExceptStatements
from pants.backend.python.tasks.future_compatibility import FutureCompatibility
from pants.backend.python.tasks.import_order import ImportOrder
from pants.backend.python.tasks.indentation import Indentation
from pants.backend.python.tasks.missing_contextmanager import MissingContextManager
from pants.backend.python.tasks.new_style_classes import NewStyleClasses
from pants.backend.python.tasks.newlines import Newlines
from pants.backend.python.tasks.pep8 import PEP8Checker
from pants.backend.python.tasks.print_statements import PrintStatements
from pants.backend.python.tasks.pyflakes import PyflakesChecker
from pants.backend.python.tasks.trailing_whitespace import TrailingWhitespace
from pants.backend.python.tasks.variable_names import PEP8VariableNames


def list_plugins():
  """Register all 'Command's from all modules in the current directory."""
  checkers = [
    ClassFactoring,
    ExceptStatements,
    FutureCompatibility,
    ImportOrder,
    Indentation,
    MissingContextManager,
    NewStyleClasses,
    Newlines,
    PEP8Checker,
    PrintStatements,
    PyflakesChecker,
    TrailingWhitespace,
    PEP8VariableNames
  ]

  # for _, mod, ispkg in pkgutil.iter_modules(__path__):
  #   if ispkg:
  #     continue
  #   fq_module = '.'.join([__name__, mod])
  #   __import__(fq_module)
  #   for (_, kls) in inspect.getmembers(sys.modules[fq_module], inspect.isclass):
  #     if kls is not CheckstylePlugin and issubclass(kls, CheckstylePlugin):
  #       checkers.append(kls)

  return checkers
