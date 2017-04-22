# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.antlr.python.python_antlr_library import PythonAntlrLibrary
from pants.base.deprecated import deprecated_module


deprecated_module('1.5.0.dev0', 'Use pants.backend.codegen.antlr.python instead')

PythonAntlrLibrary = PythonAntlrLibrary
