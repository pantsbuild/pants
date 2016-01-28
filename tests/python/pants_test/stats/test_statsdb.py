# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.stats.statsdb import StatsDB
from pants.util.contextutil import temporary_dir


def t(label, timing):
  return {'label': label, 'timing': timing}


class StatsDBTest(unittest.TestCase):
  def test_create_nonexisting_dir(self):
    # This tests that we can create a database in a directory that does not exist.
    with temporary_dir() as tmpdir:
      path = os.path.join(tmpdir, 'nonexistSubdir', 'statsdb.sqlite')
      statsdb = StatsDB(path)
      statsdb.ensure_tables()

  def test_statsdb(self):
    with temporary_dir() as tmpdir:
      path = os.path.join(tmpdir, 'statsdb.sqlite')
      statsdb = StatsDB(path)
      statsdb.ensure_tables()
      statsdb.insert_stats({
        'run_info': {
          'id': 'run1',
          'timestamp': '1438600000',
          'machine': 'ernie',
          'user': 'bert',
          'version': '9.8.7',
          'buildroot': '/path/to/repo',
          'outcome': 'SUCCESS',
          'cmd_line': 'pants compile --foo-bar baz:qux'
        },
        'cumulative_timings': [],
        'self_timings': [t('compile.java', 12.34), t('resolve.ivy', 56)]
      })
      statsdb.insert_stats({
        'run_info': {
          'id': 'run2',
          'timestamp': '1438600000',
          'machine': 'ernie',
          'user': 'bert',
          'version': '9.8.7',
          'buildroot': '/path/to/repo',
          'outcome': 'SUCCESS',
          'cmd_line': 'pants compile --foo-bar baz:qux'
        },
        'cumulative_timings': [],
        'self_timings': [t('compile.java', 9)]
      })

      stats = list(statsdb.get_stats_for_cmd_line('self_timings', '% compile %'))
      self.assertEqual(
        sorted([('compile.java', 9000), ('compile.java', 12340), ('resolve.ivy', 56000)]),
        sorted(stats))

      aggs = list(statsdb.get_aggregated_stats_for_cmd_line('self_timings', '% compile %'))
      self.assertEqual(
        sorted([('2015-08-03', 'compile.java', 2, 21340), ('2015-08-03', 'resolve.ivy', 1, 56000)]),
        sorted(aggs))
