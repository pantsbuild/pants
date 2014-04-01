# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.commands.build import Build
from pants.commands.goal import Goal
from pants.commands.help import Help
from pants.commands.py import Py
from pants.commands.setup_py import SetupPy


def register_commands():
  for cmd in (Build, Goal, Help, Py, SetupPy):
    cmd._register()
