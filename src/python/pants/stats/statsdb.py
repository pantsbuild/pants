# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sqlite3
from contextlib import contextmanager

from pants.subsystem.subsystem import Subsystem


class StatsDBError(Exception): pass


class StatsDBFactory(Subsystem):
  options_scope = 'statsdb'

  @classmethod
  def register_options(cls, register):
    super(StatsDBFactory, cls).register_options(register)
    register('--path',
             default=os.path.join(register.bootstrap.pants_bootstrapdir, 'stats', 'statsdb.sqlite'),
             help='Location of statsdb file.')

  def get_db(self):
    """Returns a StatsDB instance configured by this factory."""
    ret = StatsDB(self.get_options().path)
    ret.ensure_tables()
    return ret


class StatsDB(object):
  def __init__(self, path):
    super(StatsDB, self).__init__()
    self._path = path

  def ensure_tables(self):
    with self._cursor() as c:
      def create_index(tab, col):
        c.execute("""CREATE INDEX IF NOT EXISTS {tab}_{col}_idx ON {tab}({col})""".format(
          tab=tab, col=col))

      c.execute("""
        CREATE TABLE IF NOT EXISTS run_info (
          id TEXT PRIMARY KEY,
          timestamp INTEGER,  -- Seconds since the epoch.
          machine TEXT,
          user TEXT,
          version TEXT,
          buildroot TEXT,
          outcome TEXT,
          cmd_line TEXT
        )
      """)
      create_index('run_info', 'cmd_line')

      def create_timings_table(tab):
        c.execute("""
          CREATE TABLE IF NOT EXISTS {tab} (
            run_info_id TEXT,
            label TEXT,
            timing INTEGER,  -- Milliseconds
            FOREIGN KEY (run_info_id) REFERENCES run_info(id)
          )
        """.format(tab=tab))
        create_index(tab, 'label')

      create_timings_table('cumulative_timings')
      create_timings_table('self_timings')

  def insert_stats(self, stats):
    try:
      with self._cursor() as c:
        ri = stats['run_info']
        try:
          c.execute("""INSERT INTO run_info VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [ri['id'], int(float(ri['timestamp'])), ri['machine'], ri['user'],
                     ri['version'], ri['buildroot'], ri['outcome'], ri['cmd_line']])
        except KeyError as e:
          raise StatsDBError('Failed to insert stats. Key {} not found in RunInfo: {}'.format(
            e.args[0], str(ri)))

        rid = ri['id']
        for table in ['cumulative_timings', 'self_timings']:
          timings = stats[table]
          for timing in timings:
            try:
              c.execute("""INSERT INTO {} VALUES (?, ?, ?)""".format(table),
                        [rid, timing['label'], self._to_ms(timing['timing'])])
            except KeyError as e:
              raise StatsDBError('Failed to insert stats. Key {} not found in timing: {}'.format(
                e.args[0], str(timing)))

    except KeyError as e:
      raise StatsDBError('Failed to insert stats. Key {} not found in stats object.'.format(
        e.args[0]))

  def get_stats_for_cmd_line(self, timing_table, cmd_line_like):
    """Returns a generator over all (label, timing) pairs for a given cmd line.

    :param timing_table: One of 'cumulative_timings' or 'self_timings'.
    :param cmd_line_like: Look at all cmd lines that are LIKE this string, in the sql sense.
    """
    with self._cursor() as c:
      for row in c.execute("""
        SELECT t.label, t.timing
        FROM {} AS t INNER JOIN run_info AS ri ON (t.run_info_id=ri.id)
        WHERE ri.cmd_line LIKE ?
      """.format(timing_table), [cmd_line_like]):
        yield row

  def get_aggregated_stats_for_cmd_line(self, timing_table, cmd_line_like):
    """Returns a generator over aggregated stats for a given cmd line.

    :param timing_table: One of 'cumulative_timings' or 'self_timings'.
    :param cmd_line_like: Look at all cmd lines that are LIKE this string, in the sql sense.
    """
    with self._cursor() as c:
      for row in c.execute("""
          SELECT date(ri.timestamp, 'unixepoch') as dt, t.label as label, count(*), sum(t.timing)
          FROM {} AS t INNER JOIN run_info AS ri ON (t.run_info_id=ri.id)
          WHERE ri.cmd_line LIKE ?
          GROUP BY dt, label
          ORDER BY dt, label
        """.format(timing_table), [cmd_line_like]):
        yield row

  @staticmethod
  def _to_ms(timing_secs):
    """Convert a string representing a float of seconds to an int representing milliseconds."""
    return int(float(timing_secs) * 1000 + 0.5)

  @contextmanager
  def _connection(self):
    conn = sqlite3.connect(self._path)
    yield conn
    conn.commit()
    conn.close()

  @contextmanager
  def _cursor(self):
    with self._connection() as conn:
      yield conn.cursor()
