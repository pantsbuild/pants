# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os

from pex.interpreter import PythonIdentity, PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.python.python_repos import PythonRepos
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir_for
from pants.util.memo import memoized_method


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
      hasher.update(element)
    return hasher.hexdigest()


class SelectInterpreter(Task):
  """Select an Python interpreter that matches the constraints of all targets in the working set."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(SelectInterpreter, cls).subsystem_dependencies() + (PythonSetup, PythonRepos)

  @classmethod
  def product_types(cls):
    return [PythonInterpreter]

  def execute(self):
    interpreter = None
    python_tgts = self.context.targets(lambda tgt: isinstance(tgt, PythonTarget))
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

    if not interpreter:
      interpreter = self._get_interpreter(interpreter_path_file)

    self.context.products.get_data(PythonInterpreter, lambda: interpreter)

  @memoized_method
  def _interpreter_cache(self):
    interpreter_cache = PythonInterpreterCache(PythonSetup.global_instance(),
                                               PythonRepos.global_instance(),
                                               logger=self.context.log.debug)
    # Cache setup's requirement fetching can hang if run concurrently by another pants proc.
    self.context.acquire_lock()
    try:
      interpreter_cache.setup()
    finally:
      self.context.release_lock()
    return interpreter_cache

  def _create_interpreter_path_file(self, interpreter_path_file, targets):
    interpreter_cache = self._interpreter_cache()
    interpreter = interpreter_cache.select_interpreter_for_targets(targets)
    safe_mkdir_for(interpreter_path_file)
    with open(interpreter_path_file, 'w') as outfile:
      outfile.write(b'{}\t{}\n'.format(interpreter.binary, str(interpreter.identity)))
      for dist, location in interpreter.extras.items():
        dist_name, dist_version = dist
        outfile.write(b'{}\t{}\t{}\n'.format(dist_name, dist_version, location))

  def _interpreter_path_file(self, target_set_id):
    return os.path.join(self.workdir, target_set_id, 'interpreter.path')

  @staticmethod
  def _get_interpreter(interpreter_path_file):
    with open(interpreter_path_file, 'r') as infile:
      lines = infile.readlines()
      binary, identity = lines[0].strip().split('\t')
      extras = {}
      for line in lines[1:]:
        dist_name, dist_version, location = line.strip().split('\t')
        extras[(dist_name, dist_version)] = location
    return PythonInterpreter(binary, PythonIdentity.from_path(identity), extras)
