# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from collections import defaultdict

from s3logparse.s3logparse import parse_log_lines


class Measure:
    def __init__(self, init_count=0, init_bytes=0):
        self.count = init_count
        self.bytes = init_bytes

    def __add__(self, other):
        return self.__class__(self.count + other.count, self.bytes + other.bytes)

    def __iadd__(self, other):
        self.count += other.count
        self.bytes += other.bytes
        return self


class S3LogAccumulator:
    """Aggregates total downloaded bytes per file from S3 logs.

    Helps us track which binaries our S3 bandwidth costs are being spent on.

    To run, first download S3 access logs. For example, to download all logs for 4/2018,
    you can use something like:

    aws s3 sync s3://logs.pantsbuild.org/binaries/ /tmp/s3logs --exclude "*" --include "2018-04-*"

    Then run this binary on the downloaded logs:

    ./pants run src/python/pants/util/:s3_log_aggregator_bin -- /tmp/s3logs
    """

    def __init__(self):
        self._path_to_measure = defaultdict(Measure)
        self._ip_to_measure = defaultdict(Measure)

    def accumulate(self, logdir):
        for filename in os.listdir(logdir):
            with open(os.path.join(logdir, filename), "r") as fp:
                for log_entry in parse_log_lines(fp.readlines()):
                    m = Measure(1, log_entry.bytes_sent)
                    self._path_to_measure[log_entry.s3_key] += m
                    self._ip_to_measure[log_entry.remote_ip] += m

    def print_top_n(self, n=10):
        def do_print(heading, data):
            print()
            print(heading)
            print("=" * len(heading))
            for key, measure in data[0:n]:
                print(f"{measure.count} {self._prettyprint_bytes(measure.bytes)} {key}")

        do_print("Paths by count:", self.get_paths_sorted_by_count())
        do_print("Paths by bytes:", self.get_paths_sorted_by_bytes())
        do_print("IPs by count:", self.get_ips_sorted_by_count())
        do_print("IPs by bytes:", self.get_ips_sorted_by_bytes())
        print()

    def get_paths_sorted_by_bytes(self):
        return self._get_paths(sort_key=lambda m: m.bytes)

    def get_paths_sorted_by_count(self):
        return self._get_paths(sort_key=lambda m: m.count)

    def get_ips_sorted_by_bytes(self):
        return self._get_ips(sort_key=lambda m: m.bytes)

    def get_ips_sorted_by_count(self):
        return self._get_ips(sort_key=lambda m: m.count)

    def _get_paths(self, sort_key):
        return self._get(self._path_to_measure, sort_key)

    def _get_ips(self, sort_key):
        return self._get(self._ip_to_measure, sort_key)

    @staticmethod
    def _get(measures_map, sort_key):
        return sorted(measures_map.items(), key=lambda x: sort_key(x[1]), reverse=True)

    @staticmethod
    def _prettyprint_bytes(x):
        for unit in ["B", "KB", "MB", "GB"]:
            if abs(x) < 1024.0:
                return f"{x:3.1f}{unit}"
            x /= 1024.0
        return f"{x:.1f}TB"


if __name__ == "__main__":
    accumulator = S3LogAccumulator()
    for logdir in sys.argv[1:]:
        accumulator.accumulate(logdir)
    accumulator.print_top_n()
