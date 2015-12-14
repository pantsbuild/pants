# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.reporting.reporter import Reporter


class PlainTextReporterBase(Reporter):
  """Base class for plain-text reporting to stdout."""

  def generate_epilog(self, settings):
    ret = b''
    if settings.timing:
      ret += b'\nCumulative Timings\n==================\n{}\n'.format(
        self._format_aggregated_timings(self.run_tracker.cumulative_timings)
      )
      ret += b'\nSelf Timings\n============\n{}\n'.format(
        self._format_aggregated_timings(self.run_tracker.self_timings))
    if settings.cache_stats:
      ret += b'\nCache Stats\n===========\n{}\n'.format(
        self._format_artifact_cache_stats(self.run_tracker.artifact_cache_stats))
    ret += b'\n'
    return ret

  def _format_aggregated_timings(self, aggregated_timings):
    return b'\n'.join([b'{timing:.3f} {label}'.format(**x) for x in aggregated_timings.get_all()])

  def _format_artifact_cache_stats(self, artifact_cache_stats):
    stats = artifact_cache_stats.get_all()
    return b'No artifact cache reads.' if not stats else b'\n'.join(
      [b'{cache_name} - Hits: {num_hits} Misses: {num_misses}'.format(**x) for x in stats])
