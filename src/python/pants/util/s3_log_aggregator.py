# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from s3logparse.s3logparse import parse_log_lines

import os
import sys
from collections import defaultdict


class S3LogAccumulator(object):
  """Aggregates total downloaded bytes per file from S3 logs.

  Helps us track which binaries our S3 bandwidth costs are being spent on.

  To run, first download S3 access logs. For example, to download all logs for 4/2018,
  you can use something like:

  aws s3 sync s3://logs.pantsbuild.org/binaries/ /tmp/s3logs --exclude "*" --include "2018-04-*"

  Then run this binary on the downloaded logs:

  ./pants run src/python/pants/util/:s3_log_aggregator_bin -- /tmp/s3logs
  """

  def __init__(self):
    self._file_to_size = defaultdict(int)
    self._file_to_count = defaultdict(int)

  def accumulate(self, logdir):
    for filename in os.listdir(logdir):
      with open(os.path.join(logdir, filename)) as fp:
        for log_entry in parse_log_lines(fp.readlines()):
          self._file_to_size[log_entry.s3_key] += log_entry.bytes_sent
          self._file_to_count[log_entry.s3_key] += 1

  def get_by_size(self):
    return sorted([(path, self._file_to_count[path], size)
                   for (path, size) in self._file_to_size.items()],
                  key=lambda x: x[2], reverse=True)

  def get_by_size_prettyprinted(self):
    return [(path, count, self.prettyprint_bytes(size))
            for (path, count, size) in self.get_by_size()]

  @staticmethod
  def prettyprint_bytes(x):
    for unit in ['B', 'KB', 'MB', 'GB']:
      if abs(x) < 1024.0:
        return '{:3.1f}{}'.format(x, unit)
      x /= 1024.0
    return '{:.1f}TB'.format(x)


if __name__ == '__main__':
  accumulator = S3LogAccumulator()
  for logdir in sys.argv[1:]:
    accumulator.accumulate(logdir)

  for path, count, total_bytes in accumulator.get_by_size_prettyprinted():
    print('{} {} {}'.format(total_bytes, count, path))
