# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks import PythonBinaryCreate
from pants.base.deprecated import deprecated_module


deprecated_module('1.7.0.dev0', 'Use pants.backend.python.tasks instead')

PythonBinaryCreate = PythonBinaryCreate
