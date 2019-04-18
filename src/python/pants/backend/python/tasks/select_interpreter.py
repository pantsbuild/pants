# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import os
from builtins import open

from future.utils import PY3
from pex.executor import Executor
from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir_for


class PythonInterpreterFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):

  def compute_fingerprint(self, python_target):
    # Consider the compatibility requirements from both the targets and global constraints, as only
    # those can affect the selected interpreter.
    hash_elements_for_target = []
    if python_target.compatibility:
      hash_elements_for_target.extend(sorted(python_target.compatibility))
    if not hash_elements_for_target:
      return None
    hasher = hashlib.sha1()
    for element in hash_elements_for_target:
      hasher.update(element.encode('utf-8'))
    return hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')


class SelectInterpreter(Task):
  """Select an Python interpreter that matches the constraints of all targets in the working set."""

  @classmethod
  def implementation_version(cls):
    # TODO(John Sirois): Fixup this task to use VTS results_dirs. Right now version bumps aren't
    # effective in dealing with workdir data format changes.
    return super(SelectInterpreter, cls).implementation_version() + [('SelectInterpreter', 3)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(SelectInterpreter, cls).subsystem_dependencies() + (PythonInterpreterCache,)

  @classmethod
  def product_types(cls):
    return [PythonInterpreter]

  def execute(self):
    # NB: Downstream product consumers may need the selected interpreter for use with
    # any type of importable Python target, including `PythonRequirementLibrary` targets
    # (for use with the `repl` goal, for instance). For interpreter selection,
    # we only care about targets with compatibility constraints.
    python_tgts_and_reqs = self.context.targets(
      lambda tgt: isinstance(tgt, (PythonTarget, PythonRequirementLibrary))
    )
    if not python_tgts_and_reqs:
      return
    python_tgts = [tgt for tgt in python_tgts_and_reqs if isinstance(tgt, PythonTarget)]
    # fs = PythonInterpreterFingerprintStrategy()
    # TODO: how to merge the custom fingerprint strategy with default fingerprint() from
    # https://github.com/pantsbuild/pants/blob/7819724acb0f0e6fd83a3cd9ec6b5b72a9799721/src/python/pants/task/task.py#L310
    with self.invalidated(python_tgts) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of selecting
      # an interpreter, to prevent downstream tasks from having to check for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'
      interpreter_path_file = self._interpreter_path_file(target_set_id)
      interpreter = self._get_interpreter(interpreter_path_file, python_tgts)

    self.context.products.register_data(PythonInterpreter, interpreter)

  def _select_interpreter(self, interpreter_path_file, targets):
    interpreter_cache = PythonInterpreterCache.global_instance()
    interpreter = interpreter_cache.select_interpreter_for_targets(targets)
    safe_mkdir_for(interpreter_path_file)
    with open(interpreter_path_file, 'w') as outfile:
      outfile.write('{}\n'.format(interpreter.binary))
    return interpreter

  def _interpreter_path_file(self, target_set_id):
    # NB: The file name must be changed when its format changes. See the TODO in
    #  `implementation_version` above for more.
    #
    # The historical names to avoid:
    # - interpreter.path
    # - interpreter.info
    return os.path.join(self.workdir, target_set_id, 'interpreter.binary')

  def _get_interpreter(self, interpreter_path_file, targets):
    if os.path.exists(interpreter_path_file):
      with open(interpreter_path_file, 'r') as infile:
        binary = infile.read().strip()
      try:
        return PythonInterpreter.from_binary(binary)
      except Executor.ExecutableNotFound:
        # TODO(John Sirois): Trap a more appropriate exception once available:
        #  https://github.com/pantsbuild/pex/issues/672
        self.context.log.info('Stale interpreter reference detected: {}, removing reference and '
                              'selecting a new interpreter.'.format(binary))
        os.remove(interpreter_path_file)
    return self._select_interpreter(interpreter_path_file, targets)
