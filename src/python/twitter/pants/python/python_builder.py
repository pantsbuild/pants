# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.python.interpreter import PythonInterpreter

from pants.python.binary_builder import PythonBinaryBuilder
from pants.python.test_builder import PythonTestBuilder
from pants.targets.python_binary import PythonBinary
from pants.targets.python_tests import PythonTestSuite, PythonTests


class PythonBuilder(object):
  def __init__(self, run_tracker, root_dir):
    self._root_dir = root_dir
    self._run_tracker = run_tracker

  def build(self, targets, args, interpreter=None, conn_timeout=None):
    test_targets = []
    binary_targets = []
    interpreter = interpreter or PythonInterpreter.get()

    for target in targets:
      assert target.is_python, "PythonBuilder can only build PythonTargets, given %s" % str(target)

    # PythonBuilder supports PythonTests and PythonBinaries
    for target in targets:
      if isinstance(target, PythonTests) or isinstance(target, PythonTestSuite):
        test_targets.append(target)
      elif isinstance(target, PythonBinary):
        binary_targets.append(target)

    rv = PythonTestBuilder(
        test_targets,
        args,
        self._root_dir,
        interpreter=interpreter,
        conn_timeout=conn_timeout).run()
    if rv != 0:
      return rv

    for binary_target in binary_targets:
      rv = PythonBinaryBuilder(
          binary_target,
          self._root_dir,
          self._run_tracker,
          interpreter=interpreter,
          conn_timeout=conn_timeout).run()
      if rv != 0:
        return rv

    return 0
