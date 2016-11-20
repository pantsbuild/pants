# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem


class PyTest(Subsystem):
  options_scope = 'pytest'

  @classmethod
  def register_options(cls, register):
    super(PyTest, cls).register_options(register)
    register('--requirements', advanced=True, default='pytest>=2.6,<2.7',
             help='Requirements string for the pytest library.')
    # NB, pytest-timeout 1.0.0 introduces a conflicting pytest>=2.8.0 requirement, see:
    #   https://github.com/pantsbuild/pants/issues/2566
    register('--timeout-requirements', advanced=True, default='pytest-timeout<1.0.0',
             help='Requirements string for the pytest-timeout library.')
    register('--cov-requirements', advanced=True, default='pytest-cov>=1.8,<1.9',
             help='Requirements string for the pytest-cov library.')
    register('--unittest2-requirements', advanced=True, default='unittest2>=0.6.0,<=1.9.0',
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
