# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import os
from builtins import open

from future.utils import PY3
from pex.interpreter import PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir_for


class PythonInterpreterFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):

  def compute_fingerprint(self, python_target):
    # Only consider the compatibility requirements in the fingerprint, as only
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
    return super(SelectInterpreter, cls).implementation_version() + [('SelectInterpreter', 2)]

  @classmethod
  def subsystem_dependencies(cls):
    return super(SelectInterpreter, cls).subsystem_dependencies() + (
      PythonSetup, PythonInterpreterCache)

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
    fs = PythonInterpreterFingerprintStrategy()
    with self.invalidated(python_tgts, fingerprint_strategy=fs) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of selecting
      # an interpreter, to prevent downstream tasks from having to check for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'
      interpreter_path_file = self._interpreter_path_file(target_set_id)
      if not os.path.exists(interpreter_path_file):
        self._create_interpreter_path_file(interpreter_path_file, python_tgts)
      else:
        if self._detect_and_purge_invalid_interpreter(interpreter_path_file):
          self._create_interpreter_path_file(interpreter_path_file, python_tgts)

    interpreter = self._get_interpreter(interpreter_path_file)
    self.context.products.register_data(PythonInterpreter, interpreter)

  def _create_interpreter_path_file(self, interpreter_path_file, targets):
    interpreter_cache = PythonInterpreterCache.global_instance()
    interpreter = interpreter_cache.select_interpreter_for_targets(targets)
    safe_mkdir_for(interpreter_path_file)
    with open(interpreter_path_file, 'w') as outfile:
      outfile.write('{}\n'.format(interpreter.binary))
      for dist, location in interpreter.extras.items():
        dist_name, dist_version = dist
        outfile.write('{}\t{}\t{}\n'.format(dist_name, dist_version, location))

  def _interpreter_path_file(self, target_set_id):
    return os.path.join(self.workdir, target_set_id, 'interpreter.info')

  def _detect_and_purge_invalid_interpreter(self, interpreter_path_file):
    interpreter = self._get_interpreter(interpreter_path_file)
    if not os.path.exists(interpreter.binary):
      self.context.log.info('Stale interpreter reference detected: {}, removing reference and '
                            'selecting a new interpreter.'.format(binary))
      os.remove(interpreter_path_file)
      return True
    return False

  @staticmethod
  def _get_interpreter(interpreter_path_file):
    with open(interpreter_path_file, 'r') as infile:
      lines = infile.readlines()
      binary = lines[0].strip()
      interpreter = PythonInterpreter.from_binary(binary, include_site_extras=False)
      for line in lines[1:]:
        dist_name, dist_version, location = line.strip().split('\t')
        interpreter = interpreter.with_extra(dist_name, dist_version, location)
      return interpreter
