# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import httplib
from multiprocessing.pool import ThreadPool

from six.moves import range

from pants.util.contextutil import Timer


_global_pinger_memo = {}  # netloc -> rt time in secs.


class Pinger(object):
  # Signifies that a netloc is unreachable.
  UNREACHABLE = 999999

  def __init__(self, timeout, tries):
    """Try pinging the given number of times, each with the given timeout."""
    self._timeout = timeout
    self._tries = tries

  def ping(self, netloc):
    """Time a single roundtrip to the netloc.

    Note that we don't use actual ICMP pings, because cmd-line ping is
    inflexible and platform-dependent, so shelling out to it is annoying,
    and the ICMP python lib can only be called by the superuser.
    """
    if netloc in _global_pinger_memo:
      return _global_pinger_memo[netloc]

    host, colon, portstr = netloc.partition(':')
    port = int(portstr) if portstr else None
    rt_secs = Pinger.UNREACHABLE
    for _ in range(self._tries):
      try:
        with Timer() as timer:
          conn = httplib.HTTPConnection(host, port, timeout=self._timeout)
          conn.request('HEAD', '/')   # Doesn't actually matter if this exists.
          conn.getresponse()
        new_rt_secs = timer.elapsed
      except Exception:
        new_rt_secs = Pinger.UNREACHABLE
      rt_secs = min(rt_secs, new_rt_secs)
    _global_pinger_memo[netloc] = rt_secs
    return rt_secs

  def pings(self, netlocs):
    pool = ThreadPool(processes=len(netlocs))
    rt_secs = pool.map(self.ping, netlocs, chunksize=1)
    pool.close()
    pool.join()
    return zip(netlocs, rt_secs)
