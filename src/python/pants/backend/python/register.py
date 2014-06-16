# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.python.tasks.python_binary_create import PythonBinaryCreate
from pants.backend.python.tasks.pytest_run import PytestRun
from pants.backend.python.tasks.python_run import PythonRun
from pants.backend.python.commands.build import Build
from pants.backend.python.commands.py import Py
from pants.backend.python.commands.setup_py import SetupPy
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_requirements import python_requirements
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.setup_python_environment import SetupPythonEnvironment
from pants.commands.goal import Goal
from pants.goal import Goal as goal


def target_aliases():
  return {
    'python_binary': PythonBinary,
    'python_library': PythonLibrary,
    'python_requirement_library': PythonRequirementLibrary,
    'python_test_suite': Dependencies,  # Legacy alias.
    'python_tests': PythonTests,
  }


def object_aliases():
  return {
    'python_requirement': PythonRequirement,
    'python_artifact': PythonArtifact,
    'setup_py': PythonArtifact,
  }


def partial_path_relative_util_aliases():
  return {
    'python_requirements': python_requirements,
  }


def applicative_path_relative_util_aliases():
  return {}


def target_creation_utils():
  return {}


def register_commands():
  for cmd in (Build, Py, Goal, SetupPy):
    cmd._register()


def register_goals():
  # TODO(benjy): What is this? Do we need it?
  goal(name='python-setup', action=SetupPythonEnvironment
  ).install('setup').with_description("Setup the target's build environment.")

  goal(name='python-binary-create', action=PythonBinaryCreate, dependencies=['bootstrap', 'check-exclusives', 'resources']
  ).install('binary')

  goal(name='pytest', action=PytestRun, dependencies=['bootstrap', 'check-exclusives', 'resources']
  ).install('test')

  goal(name='python-run', action=PythonRun, dependencies=['bootstrap', 'check-exclusives', 'resources']
  ).install('run')

