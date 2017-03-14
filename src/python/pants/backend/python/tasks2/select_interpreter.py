# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os

from pex.interpreter import PythonIdentity, PythonInterpreter

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.python.python_setup import PythonRepos, PythonSetup
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
    hasher.update(python_target.payload.fingerprint())
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

  @classmethod
  def register_options(cls, register):
    super(SelectInterpreter, cls).register_options(register)
    # Note: This replaces the global --interpreter flag in the old python tasks.
    # That flag is only relevant in the python backend, and should never have been
    # global to begin with.
    register('--constraints', advanced=True, default=[], type=list,
             metavar='<requirement>',
             help="Constrain the selected Python interpreter.  Specify with requirement syntax, "
                  "e.g. 'CPython>=2.6,<3' or 'PyPy'. Multiple constraints will be ORed together. "
                  "These constraints are applied in addition to any compatibilities required by "
                  "the relevant targets.")

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
      interpreter_path_file = os.path.join(self.workdir, target_set_id, 'interpreter.path')
      if not os.path.exists(interpreter_path_file):
        interpreter_cache = PythonInterpreterCache(PythonSetup.global_instance(),
                                                   PythonRepos.global_instance(),
                                                   logger=self.context.log.debug)

        # We filter the interpreter cache itself (and not just the interpreters we pull from it)
        # because setting up some python versions (e.g., 3<=python<3.3) crashes, and this gives us
        # an escape hatch.
        filters = self.get_options().constraints or [b'']

        # Cache setup's requirement fetching can hang if run concurrently by another pants proc.
        self.context.acquire_lock()
        try:
          interpreter_cache.setup(filters=filters)
        finally:
          self.context.release_lock()

        interpreter = interpreter_cache.select_interpreter_for_targets(python_tgts)
        safe_mkdir_for(interpreter_path_file)
        with open(interpreter_path_file, 'w') as outfile:
          outfile.write(b'{}\t{}\n'.format(interpreter.binary, str(interpreter.identity)))
          for dist, location in interpreter.extras.items():
            dist_name, dist_version = dist
            outfile.write(b'{}\t{}\t{}\n'.format(dist_name, dist_version, location))

    if not interpreter:
      with open(interpreter_path_file, 'r') as infile:
        lines = infile.readlines()
        binary, identity = lines[0].strip().split('\t')
        extras = {}
        for line in lines[1:]:
          dist_name, dist_version, location = line.strip().split('\t')
          extras[(dist_name, dist_version)] = location

      interpreter = PythonInterpreter(binary, PythonIdentity.from_path(identity), extras)

    self.context.products.get_data(PythonInterpreter, lambda: interpreter)
