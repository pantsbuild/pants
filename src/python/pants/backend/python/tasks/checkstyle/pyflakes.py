# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pyflakes.checker import Checker as FlakesChecker

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin, Nit
from pants.subsystem.subsystem import Subsystem


class FlakeCheckSubsystem(Subsystem):
  options_scope = 'pycheck-pyflakes'

  @classmethod
  def register_options(cls, register):
    super(FlakeCheckSubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class FlakeError(Nit):
  # TODO(wickman) There is overlap between this and Flake8 -- consider integrating
  # checkstyle plug-ins into the PEP8 tool directly so that this can be inherited
  # by flake8.
  CLASS_ERRORS = {
    'DuplicateArgument': 'F831',
    'ImportShadowedByLoopVar': 'F402',
    'ImportStarUsed': 'F403',
    'LateFutureImport': 'F404',
    'Redefined': 'F810',
    'RedefinedInListComp': 'F812',
    'RedefinedWhileUnused': 'F811',
    'UndefinedExport': 'F822',
    'UndefinedLocal': 'F823',
    'UndefinedName': 'F821',
    'UnusedImport': 'F401',
    'UnusedVariable': 'F841',
  }

  def __init__(self, python_file, flake_message):
    super(FlakeError, self).__init__(
        self.CLASS_ERRORS.get(flake_message.__class__.__name__, 'F999'),
        Nit.ERROR,
        python_file,
        flake_message.message % flake_message.message_args,
        flake_message.lineno)


class PyflakesChecker(CheckstylePlugin):
  """Detect common coding errors via the pyflakes package."""
  subsystem = FlakeCheckSubsystem

  def nits(self):
    checker = FlakesChecker(self.python_file.tree, self.python_file.filename)
    for message in sorted(checker.messages, key=lambda msg: msg.lineno):
      yield FlakeError(self.python_file, message)
