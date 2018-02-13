# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.python.targets.python_target import PythonTarget
from pants.build_graph.target import Target
from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class TestInfraError(Exception): pass


class PythonTestInfra(Subsystem):
  options_scope = 'python-test-infra'

  @classmethod
  def register_options(cls, register):
    super(PythonTestInfra, cls).register_options(register)
    register('--pants-requirement-target', advanced=True, fingerprint=True,
             help='Address for a python target providing the pants sdist.',
             type=str, default=None)
    register('--pants-test-infra-target', advanced=True, fingerprint=True,
             help='Address for a python target providing the '
                  'pants test infra sdist.',
             type=str, default=None)

  def dependent_target_addrs(self):
    return [
      self.get_options().pants_requirement_target,
      self.get_options().pants_test_infra_target,
    ]
