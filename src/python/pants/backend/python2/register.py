# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.register import build_file_aliases as orig_build_file_aliases
from pants.backend.python.tasks.python_isort import IsortPythonTask
from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.pytest_run import PytestRun
from pants.backend.python.tasks2.python_binary_create import PythonBinaryCreate
from pants.backend.python.tasks2.python_repl import PythonRepl
from pants.backend.python.tasks2.python_run import PythonRun
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.backend.python.tasks2.setup_py import SetupPy
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return orig_build_file_aliases()


def register_goals():
  task(name='interpreter', action=SelectInterpreter).install('pyprep')
  task(name='requirements', action=ResolveRequirements).install('pyprep')
  task(name='sources', action=GatherSources).install('pyprep')
  task(name='py', action=PythonRun).install('run')
  task(name='pytest', action=PytestRun).install('test')
  task(name='py', action=PythonRepl).install('repl')
  task(name='setup-py', action=SetupPy).install()
  task(name='py', action=PythonBinaryCreate).install('binary')
  task(name='isort', action=IsortPythonTask).install('fmt')

  # Integration tests of the new pipeline still use the `*2` aliases.
  task(name='py', action=PythonRun).install('run2')
  task(name='pytest', action=PytestRun).install('test2')
  task(name='py', action=PythonRepl).install('repl2')
  task(name='py', action=PythonBinaryCreate).install('binary2')
  task(name='setup-py2', action=SetupPy).install()
