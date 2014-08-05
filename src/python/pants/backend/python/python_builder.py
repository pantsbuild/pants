# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pex.interpreter import PythonInterpreter

from pants.backend.python.binary_builder import PythonBinaryBuilder
from pants.backend.python.test_builder import PythonTestBuilder
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_tests import PythonTests


class PythonBuilder(object):
  def __init__(self, run_tracker):
    self._run_tracker = run_tracker

  def build(self, targets, args, interpreter=None, conn_timeout=None, fast_tests=False):
    test_targets = []
    binary_targets = []
    interpreter = interpreter or PythonInterpreter.get()

    for target in targets:
      assert target.is_python, "PythonBuilder can only build PythonTargets, given %s" % str(target)

    # PythonBuilder supports PythonTests and PythonBinaries
    for target in targets:
      if isinstance(target, PythonTests):
        test_targets.append(target)
      elif isinstance(target, PythonBinary):
        binary_targets.append(target)

    rv = PythonTestBuilder(
        test_targets,
        args,
        interpreter=interpreter,
        conn_timeout=conn_timeout,
        fast=fast_tests).run()
    if rv != 0:
      return rv

    for binary_target in binary_targets:
      rv = PythonBinaryBuilder(
          binary_target,
          self._run_tracker,
          interpreter=interpreter,
          conn_timeout=conn_timeout).run()
      if rv != 0:
        return rv

    return 0
