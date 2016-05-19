# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import urlparse
from collections import Counter, deque
from contextlib import contextmanager
from multiprocessing.pool import ThreadPool

import requests
from six.moves import range

from pants.cache.artifact_cache import ArtifactCacheError
from pants.util.contextutil import Timer
from pants.util.memo import memoized_method


class InvalidRESTfulCacheProtoError(ArtifactCacheError):
  """Indicates an invalid protocol used in a remote spec."""
  pass


class Pinger(object):
  # Signifies that a netloc is unreachable.
  UNREACHABLE = 999999

  @classmethod
  def _try_ping(cls, url, timeout):
    try:
      with Timer() as timer:
        # We just want to see if we can get the headers.
        requests.head(url, timeout=timeout)
      return timer.elapsed
    except Exception:
      return Pinger.UNREACHABLE

  @classmethod
  @memoized_method
  def _get_ping_time(cls, url, timeout, tries):
    rt_secs = Pinger.UNREACHABLE
    for _ in range(tries):
      rt_secs = min(rt_secs, cls._try_ping(url, timeout))
    return rt_secs

  def __init__(self, timeout, tries):
    """Try pinging the given number of times, each with the given timeout."""
    self._timeout = timeout
    self._tries = tries

  def ping(self, url):
    """Time a single roundtrip to the url.

    :param url to ping.
    :returns: the fastest ping time for a given netloc and number of tries.
    or Pinger.UNREACHABLE if ping times out.
    :rtype: float

    Note that we don't use actual ICMP pings, because cmd-line ping is
    inflexible and platform-dependent, so shelling out to it is annoying,
    and the ICMP python lib can only be called by the superuser.
    """
    return self._get_ping_time(url, self._timeout, self._tries)

  def pings(self, urls):
    pool = ThreadPool(processes=len(urls))
    rt_secs = pool.map(self.ping, urls, chunksize=1)
    pool.close()
    pool.join()
    return zip(urls, rt_secs)


class BestUrlSelector(object):
  SUPPORTED_PROTOCOLS = ('http', 'https')
  MAX_FAILURES = 3

  def __init__(self, available_urls, max_failures=MAX_FAILURES):
    """Save parsed input urls in order and perform basic validations.

    :param available_urls: input urls pre-sorted by their ping times.
    """

    if len(available_urls) == 0:
      raise ValueError('BestUrlSelector requires at least one url to select from.')

    self.parsed_urls = deque(self._parse_urls(available_urls))
    self.unsuccessful_calls = Counter()
    self.max_failures = max_failures

  def _parse_urls(self, urls):
    parsed_urls = [urlparse.urlparse(url) for url in urls]
    for parsed_url in parsed_urls:
      if not parsed_url.scheme in self.SUPPORTED_PROTOCOLS:
        raise InvalidRESTfulCacheProtoError(
          'RESTfulArtifactCache only supports HTTP(S). Found: {0}'.format(parsed_url.scheme))
    return parsed_urls

  @contextmanager
  def select_best_url(self):
    """Select `best` url.

    Since urls are pre-sorted w.r.t. their ping times, we simply return the first element
    from the list. And we always return the same url unless we observe greater than max
    allowed number of consecutive failures. In this case, we would return the next `best`
    url, and append the previous best one to the end of list (essentially rotate to the left
    by one element).
    """

    best_url = self.parsed_urls[0]
    try:
      yield best_url
    except Exception:
      self.unsuccessful_calls[best_url] += 1

      # Not thread-safe but pool used by cache is based on subprocesses, therefore no race.
      if self.unsuccessful_calls[best_url] > self.max_failures:
        self.parsed_urls.rotate(-1)
        self.unsuccessful_calls[best_url] = 0
      raise
    else:
      self.unsuccessful_calls[best_url] = 0
