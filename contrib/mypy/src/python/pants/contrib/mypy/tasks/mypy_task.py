# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from typing import List

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.contextutil import temporary_file_path
from pants.util.memo import memoized_property
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_info import PexInfo


class MypyTaskError(TaskError):
  """Indicates a TaskError from a failing MyPy run."""


class MypyTask(LintTaskMixin, ResolveRequirementsTaskBase):
  """Invoke the mypy static type analyzer for Python.

  Mypy lint task filters out target_roots that are not properly tagged according to
  --whitelisted-tag-name (defaults to None, and no filtering occurs if this option is 'None'),
  and executes MyPy on targets in context from whitelisted target roots.
  (if any transitive targets from the filtered roots are not whitelisted, a warning
  will be printed.)

  'In context' meaning in the sub-graph where a whitelisted target is the root
  """

  _MYPY_COMPATIBLE_INTERPETER_CONSTRAINT = '>=3.5'
  _PYTHON_SOURCE_EXTENSION = '.py'

  deprecated_options_scope = 'mypy'
  deprecated_options_scope_removal_version = '1.21.0.dev0'

  WARNING_MESSAGE = "[WARNING]: Targets not currently whitelisted and may cause issues."

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require_data(PythonInterpreter)

  @classmethod
  def register_options(cls, register):
    register('--mypy-version', default='0.710', help='The version of mypy to use.')
    register('--config-file', default=None,
             help='Path mypy configuration file, relative to buildroot.')
    register('--whitelist-tag-name', default=None,
             help='Tag name to identify python targets to execute MyPy')
    register('--verbose', type=bool, default=False,
             help='Extra detail showing non-whitelisted targets')

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (PythonInterpreterCache,)

  def find_mypy_interpreter(self):
    interpreters = self._interpreter_cache.setup(
      filters=[self._MYPY_COMPATIBLE_INTERPETER_CONSTRAINT]
    )
    return min(interpreters) if interpreters else None

  @staticmethod
  def is_non_synthetic_python_target(target):
    return (not target.is_synthetic and
            isinstance(target, (PythonLibrary, PythonBinary, PythonTests)))

  @staticmethod
  def is_python_target(target):
    return isinstance(target, PythonTarget)

  def _is_tagged_target(self, target: Target) -> bool:
    return self.get_options().whitelist_tag_name in target.tags

  def _is_tagged_non_synthetic_python_target(self, target: Target) -> bool:
    return (self.is_non_synthetic_python_target(target) and
            self._is_tagged_target(target))

  def _not_tagged_non_synthetic_python_target(self, target: Target) -> bool:
    return (self.is_non_synthetic_python_target(target) and
            not self._is_tagged_target(target))

  def _all_targets_are_whitelisted(self, whitelisted_targets: List[Target], all_targets: List[Target]) -> bool:
    return len(whitelisted_targets) == 0 or len(whitelisted_targets) == len(all_targets)

  def _format_targets_not_whitelisted(self, targets: List[Target]) -> str:
    output = ''
    for target in targets:
      output = output + f"{target.address.spec}\n"
    return output

  def _whitelist_warning(self, targets_not_whitelisted: List[Target]) -> None:
    self.context.log.warn(self.WARNING_MESSAGE)
    if self.get_options().verbose:
      output = self._format_targets_not_whitelisted(targets_not_whitelisted)
      self.context.log.warn(f"{output}")

  def _calculate_python_sources(self, target_roots: List[Target]):
    """Filter targets to generate a set of source files from the given targets."""
    if self.get_options().whitelist_tag_name:
      all_targets = self._filter_targets(Target.closure_for_targets([tgt for tgt in target_roots if self._is_tagged_target(tgt)]))
      python_eval_targets = [tgt for tgt in all_targets if self._is_tagged_non_synthetic_python_target(tgt)]
      if not self._all_targets_are_whitelisted(python_eval_targets, all_targets):
        targets_not_whitelisted = [tgt for tgt in all_targets if self._not_tagged_non_synthetic_python_target(tgt)]
        self._whitelist_warning(targets_not_whitelisted)
    else:
      python_eval_targets = self._filter_targets([tgt for tgt in Target.closure_for_targets(target_roots) if self.is_non_synthetic_python_target(tgt)])

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
    return PythonInterpreterCache.global_instance()

  def _run_mypy(self, py3_interpreter, mypy_args, **kwargs):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'mypy'
    mypy_version = self.get_options().mypy_version

    mypy_requirement_pex = self.resolve_requirement_strings(
      py3_interpreter, [f'mypy=={mypy_version}'])

    path = os.path.realpath(os.path.join(self.workdir, str(py3_interpreter.identity), mypy_version))
    if not os.path.isdir(path):
      self.merge_pexes(path, pex_info, py3_interpreter, [mypy_requirement_pex])
    pex = PEX(path, py3_interpreter)
    return pex.run(mypy_args, **kwargs)

  def execute(self):
    mypy_interpreter = self.find_mypy_interpreter()
    if not mypy_interpreter:
      raise TaskError(f'Unable to find a Python {self._MYPY_COMPATIBLE_INTERPETER_CONSTRAINT} '
                      f'interpreter (required for mypy).')

    sources = self._calculate_python_sources(self.context.target_roots)
    if not sources:
      self.context.log.debug('No Python sources to check.')
      return

    # Determine interpreter used by the sources so we can tell mypy.
    interpreter_for_targets = self._interpreter_cache.select_interpreter_for_targets(
      self.context.target_roots
    )
    if not interpreter_for_targets:
      raise TaskError('No Python interpreter compatible with specified sources.')

    with temporary_file_path() as sources_list_path:
      with open(sources_list_path, 'w') as f:
        for source in sources:
          f.write(f'{source}\n')
      # Construct the mypy command line.
      cmd = [f'--python-version={interpreter_for_targets.identity.python}']
      if self.get_options().config_file:
        cmd.append(f'--config-file={os.path.join(get_buildroot(), self.get_options().config_file)}')
      cmd.extend(self.get_passthru_args())
      cmd.append(f'@{sources_list_path}')
      self.context.log.debug(f'mypy command: {" ".join(cmd)}')

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
        returncode = self._run_mypy(mypy_interpreter, cmd,
          env={'MYPYPATH': mypy_path}, stdout=workunit.output('stdout'), stderr=subprocess.STDOUT)
        if returncode != 0:
          raise MypyTaskError(f'mypy failed: code={returncode}')
