# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pyflakes.checker import Checker as FlakesChecker

from pants.contrib.python.checks.checker.common import CheckstylePlugin, Nit


class FlakeError(Nit):
    # TODO(wickman) There is overlap between this and Flake8 -- consider integrating
    # checkstyle plug-ins into the PEP8 tool directly so that this can be inherited
    # by flake8.
    # Code reference is here: https://github.com/PyCQA/pyflakes/blob/master/pyflakes/messages.py
    CLASS_ERRORS = {
        "DuplicateArgument": "F831",
        "ImportShadowedByLoopVar": "F402",
        "ImportStarUsed": "F403",
        "LateFutureImport": "F404",
        "Redefined": "F810",
        "RedefinedInListComp": "F812",
        "RedefinedWhileUnused": "F811",
        "UndefinedExport": "F822",
        "UndefinedLocal": "F823",
        "UndefinedName": "F821",
        "UnusedImport": "F401",
        "UnusedVariable": "F841",
    }

    def __init__(self, python_file, flake_message):
        line_range = python_file.line_range(flake_message.lineno)
        super(FlakeError, self).__init__(
            self.get_error_code(flake_message),
            Nit.ERROR,
            python_file.filename,
            flake_message.message % flake_message.message_args,
            line_range,
            python_file.lines[line_range],
        )

    @classmethod
    def is_ignored(cls, ignore_list, message):
        name = message.__class__.__name__
        err_code = cls.get_error_code(message)
        # TODO: The ignore list should be a set.
        return any(i == err_code or i == name for i in ignore_list)

    @classmethod
    def get_error_code(cls, message):
        return cls.CLASS_ERRORS.get(message.__class__.__name__, "F999")


class PyflakesChecker(CheckstylePlugin):
    """Detect common coding errors via the pyflakes package."""

    @classmethod
    def name(cls):
        return "pyflakes"

    def nits(self):
        checker = FlakesChecker(self.python_file.tree, self.python_file.filename)
        for message in sorted(checker.messages, key=lambda msg: msg.lineno):
            if not FlakeError.is_ignored(self.options.ignore, message):
                yield FlakeError(self.python_file, message)
