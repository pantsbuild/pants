# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CleanAllTest(PantsRunIntegrationTest):
  def gen_ivy_option(self, f):
    return '--ivy-cache-dir={}'.format(f)

  def test_optional_removal_positive(self):
    """Verify that directories are moved when specified"""
    with temporary_dir() as cache_dir:
      with temporary_dir() as ivy_dir:
        pex_dir = os.environ.get('PEX_ROOT')
        config = {
          'cache': {'write_to': [cache_dir],
                    'read_from': [cache_dir]},
        }

        pants_run = self.run_pants(['clean-all',
                                    '--no-skip-buildcache',
                                    '--no-skip-ivy',
                                    '--no-skip-pex',
                                    self.gen_ivy_option(ivy_dir)
                                    ],
                                   config=config)
        print()
        map(print,pants_run.stdout_data.split('\n'))
        self.assert_success(pants_run)

        assert not os.path.exists(cache_dir), 'Cache dir still exists'.format(cache_dir)
        assert not os.path.exists(ivy_dir), 'Ivy dir still exists {}'.format(ivy_dir)

  def test_optional_removal_negative(self):
    """Verify that directories are left alone if skipped"""
    with temporary_dir() as cache_dir:
      with temporary_dir() as ivy_dir:
        config = {
          'cache': {'write_to': [cache_dir],
                    'read_from': [cache_dir]},
          'ivy': {'cache_dir': [ivy_dir]}
        }

        pants_run = self.run_pants(['clean-all',
                                    '--skip-buildcache',
                                    '--skip-ivy',
                                    '--skip-pex',
                                    ],
                                   config=config)
        self.assert_success(pants_run)

        self.assertTrue(os.path.exists(cache_dir))
        self.assertTrue(os.path.exists(ivy_dir))
