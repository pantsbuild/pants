# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.subsystem.subsystem import Subsystem


class PyTest(Subsystem):
  options_scope = 'pytest'

  @classmethod
  def register_options(cls, register):
    super(PyTest, cls).register_options(register)
    register('--requirements', advanced=True, default='pytest==4.5.0',
             help='Requirements string for the pytest library.')
    register('--timeout-requirements', advanced=True, default='pytest-timeout==1.3.3',
             help='Requirements string for the pytest-timeout library.')
    register('--cov-requirements', advanced=True, default='pytest-cov==2.7.1',
             help='Requirements string for the pytest-cov library.')
    register('--unittest2-requirements', advanced=True, default='unittest2==1.1.0',
             help='Requirements string for the unittest2 library, which some python versions '
                  'may need.')

  def get_requirement_strings(self):
    """Returns a tuple of requirements-style strings for pytest and related libraries.

    Make sure the requirements are satisfied in any environment used for running tests.
    """
    opts = self.get_options()
    return (
      opts.requirements,
      opts.timeout_requirements,
      opts.cov_requirements,
      opts.unittest2_requirements,
    )
