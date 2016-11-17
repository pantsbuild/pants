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
    register('--pytest-requirements', default='pytest>=2.6,<2.7',
             help='Requirements string for the pytest library.')
    # NB, pytest-timeout 1.0.0 introduces a conflicting pytest>=2.8.0 requirement, see:
    #   https://github.com/pantsbuild/pants/issues/2566
    register('--pytest-timeout-requirements', default='pytest-timeout<1.0.0',
             help='Requirements string for the pytest-timeout library.')
    register('--pytest-cov-requirements', default='pytest-cov>=1.8,<1.9',
             help='Requirements string for the pytest-cov library.')
    register('--unittest2-requirements', default='unittest2>=0.6.0,<=1.9.0',
             help='Requirements string for the unittest2 library, which some python versions '
                  'may need.')

  def get_requirement_strings(self):
    opts = self.get_options()
    return (
      opts.pytest_requirements,
      opts.pytest_timeout_requirements,
      opts.pytest_cov_requirements,
      opts.unittest2_requirements,
    )
