# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


logger = logging.getLogger(__name__)


class Conan(PythonToolBase):
  options_scope = 'conan'
  default_requirements = [
    'conan==1.9.2',
    # NB: Only versions of pylint below `2.0.0` support use in python 2.
    'pylint==1.9.3',
  ]
  default_entry_point = 'conans.conan'
  default_interpreter_constraints = ['CPython>=2.7,<4']
