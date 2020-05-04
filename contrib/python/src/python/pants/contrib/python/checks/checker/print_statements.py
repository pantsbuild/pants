# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import re

from six import PY2

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class PrintStatements(CheckstylePlugin):
    """Enforce the use of print as a function and not a statement."""

    @classmethod
    def name(cls):
        return "print-statements"

    FUNCTIONY_EXPRESSION = re.compile(r"^\s*\(.*\)\s*$")

    def nits(self):
        if not PY2:
            # Python 3+ interpreters will raise SyntaxError upon reading a print statement.
            # So, this module cannot be meaningfully used when run with a Python 3+ interpreter.
            return
        # MyPy says this is unreachable when run with Python 3+.
        for print_node in self.iter_ast_types(ast.Print):  # type: ignore[unreachable]
            # In Python 2.x print calls can be written as function calls when the __future__
            # print_function is imported. Ensure all print calls are function calls, disallowing
            # legacy print statements.
            logical_line = "".join(self.python_file[print_node.lineno])
            print_offset = logical_line.index("print")
            stripped_line = logical_line[print_offset + len("print") :]
            if not self.FUNCTIONY_EXPRESSION.match(stripped_line):
                yield self.error("T607", "Print used as a statement.", print_node)
