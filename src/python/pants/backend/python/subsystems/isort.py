# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Isort(PythonToolBase):
  options_scope = 'isort'
  default_requirements = ['isort==4.3.20', 'setuptools']
  default_entry_point = 'isort.main'
