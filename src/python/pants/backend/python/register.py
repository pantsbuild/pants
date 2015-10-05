# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_requirements import python_requirements
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.pytest_run import PytestRun
from pants.backend.python.tasks.python_binary_create import PythonBinaryCreate
from pants.backend.python.tasks.python_repl import PythonRepl
from pants.backend.python.tasks.python_run import PythonRun
from pants.backend.python.tasks.setup_py import SetupPy
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'python_binary': PythonBinary,
      'python_library': PythonLibrary,
      'python_requirement_library': PythonRequirementLibrary,
      'python_test_suite': Dependencies,  # Legacy alias.
      'python_tests': PythonTests,
    },
    objects={
      'python_requirement': PythonRequirement,
      'python_artifact': PythonArtifact,
      'setup_py': PythonArtifact,
    },
    context_aware_object_factories={
      'python_requirements': BuildFileAliases.curry_context(python_requirements),
    }
  )


def register_goals():
  task(name='python-binary-create', action=PythonBinaryCreate).install('binary')
  task(name='pytest', action=PytestRun).install('test')
  task(name='py', action=PythonRun).install('run')
  task(name='py', action=PythonRepl).install('repl')
  task(name='setup-py', action=SetupPy).install().with_description(
    'Build setup.py-based Python projects from python_library targets.')
