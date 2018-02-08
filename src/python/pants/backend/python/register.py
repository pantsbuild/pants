# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.pants_requirement import PantsRequirement
from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_requirements import PythonRequirements
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.build_local_python_distributions import \
  BuildLocalPythonDistributions
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.pytest_prep import PytestPrep
from pants.backend.python.tasks.pytest_run import PytestRun
from pants.backend.python.tasks.python_binary_create import PythonBinaryCreate
from pants.backend.python.tasks.python_isort import IsortPythonTask
from pants.backend.python.tasks.python_repl import PythonRepl
from pants.backend.python.tasks.python_run import PythonRun
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.backend.python.tasks.setup_py import SetupPy
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      PythonBinary.alias(): PythonBinary,
      PythonLibrary.alias(): PythonLibrary,
      PythonTests.alias(): PythonTests,
      PythonDistribution.alias(): PythonDistribution,
      'python_requirement_library': PythonRequirementLibrary,
      Resources.alias(): Resources,
    },
    objects={
      'python_requirement': PythonRequirement,
      'python_artifact': PythonArtifact,
      'setup_py': PythonArtifact,
    },
    context_aware_object_factories={
      'python_requirements': PythonRequirements,
      'pants_requirement': PantsRequirement,
    }
  )


def register_goals():
  task(name='interpreter', action=SelectInterpreter).install('pyprep')
  task(name='build-local-dists', action=BuildLocalPythonDistributions).install('pyprep')
  task(name='requirements', action=ResolveRequirements).install('pyprep')
  task(name='sources', action=GatherSources).install('pyprep')
  task(name='py', action=PythonRun).install('run')
  task(name='pytest-prep', action=PytestPrep).install('test')
  task(name='pytest', action=PytestRun).install('test')
  task(name='py', action=PythonRepl).install('repl')
  task(name='setup-py', action=SetupPy).install()
  task(name='py', action=PythonBinaryCreate).install('binary')
  task(name='isort', action=IsortPythonTask).install('fmt')
