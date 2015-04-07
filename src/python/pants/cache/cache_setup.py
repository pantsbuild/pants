# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import urlparse

from six.moves import range

from pants.cache.artifact_cache import ArtifactCacheError
from pants.cache.local_artifact_cache import LocalArtifactCache, TempLocalArtifactCache
from pants.cache.pinger import Pinger
from pants.cache.restful_artifact_cache import RESTfulArtifactCache


class EmptyCacheSpecError(ArtifactCacheError):
  pass
class LocalCacheSpecRequiredError(ArtifactCacheError):
  pass
class CacheSpecFormatError(ArtifactCacheError):
  pass
class InvalidCacheSpecError(ArtifactCacheError):
  pass
class RemoteCacheSpecRequiredError(ArtifactCacheError):
  pass


def select_best_url(spec, pinger, log):
  urls = spec.split('|')
  if len(urls) == 1:
    return urls[0]  # No need to ping if we only have one option anyway.
  netlocs = map(lambda url: urlparse.urlparse(url)[1], urls)
  pingtimes = pinger.pings(netlocs)  # List of pairs (host, time in ms).
  log.debug('Artifact cache server ping times: {}'
            .format(', '.join(['{}: {:3} secs'.format(*p) for p in pingtimes])))
  argmin = min(range(len(pingtimes)), key=lambda i: pingtimes[i][1])
  best_url = urls[argmin]
  if pingtimes[argmin][1] == Pinger.UNREACHABLE:
    return None  # No reachable artifact caches.
  log.debug('Best artifact cache is {0}'.format(best_url))
  return best_url


def create_artifact_cache(log, artifact_root, spec, task_name, compression,
                          action='using', local=None):
  """Returns an artifact cache for the specified spec.

  spec can be:
    - a path to a file-based cache root.
    - a URL of a RESTful cache root.
    - a bar-separated list of URLs, where we'll pick the one with the best ping times.
    - A list or tuple of two specs, local, then remote, each as described above

  :param log: context.log
  :param str artifact_root: The path under which cacheable products will be read/written.
  :param str spec: See above.
  :param str task_name: The name of the task using this cache (eg 'ScalaCompile')
  :param int compression: The gzip compression level for created artifacts.
                          Valid values are 0-9.  0 means that gzip is used in a mode where it
                          does not compress the input data; this is used for its side-effect of
                          providing checksums.
  :param str action: A verb, eg 'read' or 'write' for printed messages.
  :param LocalArtifactCache local: A local cache for use by created remote caches
  """
  if not spec:
    raise EmptyCacheSpecError()
  if compression not in range(10):
    raise ValueError('compression value must be an integer between 0 and 9 inclusive: {com}'.format(
      com=compression))

  def recurse(new_spec, new_local=local):
    return create_artifact_cache(log=log, artifact_root=artifact_root, spec=new_spec,
                                 task_name=task_name, compression=compression, action=action,
                                 local=new_local)

  def is_remote(spec):
    return spec.startswith('http://') or spec.startswith('https://')

  if isinstance(spec, basestring):
    if spec.startswith('/') or spec.startswith('~'):
      path = os.path.join(spec, task_name)
      log.debug('{0} {1} local artifact cache at {2}'.format(task_name, action, path))
      return LocalArtifactCache(artifact_root, path, compression)
    elif is_remote(spec):
      # Caches are supposed to be close, and we don't want to waste time pinging on no-op builds.
      # So we ping twice with a short timeout.
      pinger = Pinger(timeout=0.5, tries=2)
      best_url = select_best_url(spec, pinger, log)
      if best_url:
        url = best_url.rstrip('/') + '/' + task_name
        log.debug('{0} {1} remote artifact cache at {2}'.format(task_name, action, url))
        local = local or TempLocalArtifactCache(artifact_root, compression)
        return RESTfulArtifactCache(artifact_root, url, local)
      else:
        log.warn('{0} has no reachable artifact cache in {1}.'.format(task_name, spec))
        return None
    else:
      raise CacheSpecFormatError('Invalid artifact cache spec: {0}'.format(spec))
  elif isinstance(spec, (list, tuple)) and len(spec) is 1:
    return recurse(spec[0])
  elif isinstance(spec, (list, tuple)) and len(spec) is 2:
    first = recurse(spec[0])
    if not isinstance(first, LocalArtifactCache):
      raise LocalCacheSpecRequiredError(
        'First of two cache specs must be a local cache path. Found: {0}'.format(spec[0]))
    if not is_remote(spec[1]):
      raise RemoteCacheSpecRequiredError(
        'Second of two cache specs must be a remote spec. Found: {0}'.format(spec[1]))
    return recurse(spec[1], new_local=first)
  else:
    raise InvalidCacheSpecError('Invalid artifact cache spec: {0}'.format(spec))
