# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import filter, open, str

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.contextutil import temporary_file_path
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_info import PexInfo


class MypyTask(ResolveRequirementsTaskBase):
  """Invoke the mypy static type analyzer for Python."""

  _PYTHON_SOURCE_EXTENSION = '.py'

  @classmethod
  def prepare(cls, options, round_manager):
    super(MypyTask, cls).prepare(options, round_manager)
    round_manager.require_data(PythonInterpreter)

  @classmethod
  def register_options(cls, register):
    register('--mypy-version', default='0.550', help='The version of mypy to use.')
    register('--config-file', default=None,
             help='Path mypy configuration file, relative to buildroot.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def find_py3_interpreter(self):
    interpreters = self._interpreter_cache.setup(filters=['>=3'])
    return min(interpreters) if interpreters else None

  @staticmethod
  def is_non_synthetic_python_target(target):
    return (not target.is_synthetic and
            isinstance(target, (PythonLibrary, PythonBinary, PythonTests)))

  @staticmethod
  def is_python_target(target):
    return isinstance(target, PythonTarget)

  def _calculate_python_sources(self, targets):
    """Generate a set of source files from the given targets."""
    python_eval_targets = filter(self.is_non_synthetic_python_target, targets)
    sources = set()
    for target in python_eval_targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return list(sources)

  def _collect_source_roots(self):
    # Collect the set of directories in which there are Python sources (whether part of
    # the target roots or transitive dependencies.)
    source_roots = set()
    for target in self.context.targets(self.is_python_target):
      if not target.has_sources(self._PYTHON_SOURCE_EXTENSION):
        continue
      source_roots.add(target.target_base)
    return source_roots

  @memoized_property
  def _interpreter_cache(self):
    return PythonInterpreterCache(PythonSetup.global_instance(),
                                  PythonRepos.global_instance(),
                                  logger=self.context.log.debug)

  def _run_mypy(self, py3_interpreter, mypy_args, **kwargs):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'mypy'
    mypy_version = self.get_options().mypy_version

    mypy_requirement_pex = self.resolve_requirement_strings(
      py3_interpreter, ['mypy=={}'.format(mypy_version)])

    path = os.path.realpath(os.path.join(self.workdir, str(py3_interpreter.identity), mypy_version))
    if not os.path.isdir(path):
      self.merge_pexes(path, pex_info, py3_interpreter, [mypy_requirement_pex])
    pex = PEX(path, py3_interpreter)
    return pex.run(mypy_args, **kwargs)

  def execute(self):
    py3_interpreter = self.find_py3_interpreter()
    if not py3_interpreter:
      raise TaskError('Unable to find a Python 3.x interpreter (required for mypy).')

    sources = self._calculate_python_sources(self.context.target_roots)
    if not sources:
      self.context.log.debug('No Python sources to check.')
      return

    # Determine interpreter used by the sources so we can tell mypy.
    interpreter_for_targets = self._interpreter_cache.select_interpreter_for_targets(self.context.target_roots)
    if not interpreter_for_targets:
      raise TaskError('No Python interpreter compatible with specified sources.')

    with temporary_file_path() as sources_list_path:
      with open(sources_list_path, 'w') as f:
        for source in sources:
          f.write('{}\n'.format(source))

      # Construct the mypy command line.
      cmd = ['--python-version={}'.format(interpreter_for_targets.identity.python)]
      if self.get_options().config_file:
        cmd.append('--config-file={}'.format(os.path.join(get_buildroot(),
                                                          self.get_options().config_file)))
      cmd.extend(self.get_passthru_args())
      cmd.append('@{}'.format(sources_list_path))
      self.context.log.debug('mypy command: {}'.format(' '.join(cmd)))

      # Collect source roots for the targets being checked.
      source_roots = self._collect_source_roots()

      mypy_path = os.pathsep.join([os.path.join(get_buildroot(), root) for root in source_roots])

      # Execute mypy.
      with self.context.new_workunit(
        name='check',
        labels=[WorkUnitLabel.TOOL, WorkUnitLabel.RUN],
        log_config=WorkUnit.LogConfig(level=self.get_options().level,
                                      colors=self.get_options().colors),
        cmd=' '.join(cmd)) as workunit:
        returncode = self._run_mypy(py3_interpreter, cmd,
          env={'MYPYPATH': mypy_path}, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)
        if returncode != 0:
          raise TaskError('mypy failed: code={}'.format(returncode))
