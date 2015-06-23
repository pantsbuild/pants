# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import threading
import urlparse

from six import string_types
from six.moves import range

from pants.cache.artifact_cache import ArtifactCacheError
from pants.cache.local_artifact_cache import LocalArtifactCache, TempLocalArtifactCache
from pants.cache.pinger import Pinger
from pants.cache.restful_artifact_cache import RESTfulArtifactCache
from pants.option.options import Options
from pants.subsystem.subsystem import Subsystem


class EmptyCacheSpecError(ArtifactCacheError): pass
class LocalCacheSpecRequiredError(ArtifactCacheError): pass
class CacheSpecFormatError(ArtifactCacheError): pass
class InvalidCacheSpecError(ArtifactCacheError): pass
class RemoteCacheSpecRequiredError(ArtifactCacheError): pass



class CacheSetup(Subsystem):
  options_scope = 'cache'

  @classmethod
  def register_options(cls, register):
    super(CacheSetup, cls).register_options(register)
    register('--read', action='store_true', default=True, recursive=True,
             help='Read build artifacts from cache, if available.')
    register('--write', action='store_true', default=True, recursive=True,
             help='Write build artifacts to cache, if available.')
    register('--overwrite', action='store_true', recursive=True,
             help='If writing build artifacts to cache, overwrite existing artifacts '
                  'instead of skipping them.')
    register('--read-from', type=Options.list, recursive=True,
             help='The URIs of artifact caches to read from. Each entry is a URL of a RESTful '
                  'cache, a path of a filesystem cache, or a pipe-separated list of alternate '
                  'caches to choose from.')
    register('--write-to', type=Options.list, recursive=True,
             help='The URIs of artifact caches to write to. Each entry is a URL of a RESTful '
                  'cache, a path of a filesystem cache, or a pipe-separated list of alternate '
                  'caches to choose from.')
    register('--compression-level', advanced=True, type=int, default=5, recursive=True,
             help='The gzip compression level (0-9) for created artifacts.')

  @classmethod
  def create_cache_factory_for_task(cls, task):
    return CacheFactory(cls.instance_for_task(task).get_options(),
                        task.context.log, task.stable_name())


class CacheFactory(object):
  def __init__(self, options, log, stable_name, pinger=None):
    self._options = options
    self._log = log
    self._stable_name = stable_name

    # Created on-demand.
    self._read_cache = None
    self._write_cache = None

    # Protects local filesystem setup, and assignment to the references above.
    self._cache_setup_lock = threading.Lock()

    # Caches are supposed to be close, and we don't want to waste time pinging on no-op builds.
    # So we ping twice with a short timeout.
    # TODO: Make lazy.
    self._pinger = pinger or Pinger(timeout=0.5, tries=2)

  def read_cache_available(self):
    return self._options.read and bool(self._options.read_from)

  def write_cache_available(self):
    return self._options.write and bool(self._options.write_to)

  def overwrite(self):
    return self._options.overwrite

  def get_read_cache(self):
    """Returns the read cache for this setup, creating it if necessary.

    Returns None if no read cache is configured.
    """
    if self._options.read_from and not self._read_cache:
      with self._cache_setup_lock:
        self._read_cache = self._do_create_artifact_cache(self._options.read_from, 'will read from')
    return self._read_cache

  def get_write_cache(self):
    """Returns the write cache for this setup, creating it if necessary.

    Returns None if no read cache is configured.
    """
    if self._options.write_to and not self._write_cache:
      with self._cache_setup_lock:
        self._write_cache = self._do_create_artifact_cache(self._options.write_to, 'will write to')
    return self._write_cache

  def select_best_url(self, spec):
    urls = spec.split('|')
    if len(urls) == 1:
      return urls[0]  # No need to ping if we only have one option anyway.
    netlocs = map(lambda url: urlparse.urlparse(url)[1], urls)
    pingtimes = self._pinger.pings(netlocs)  # List of pairs (host, time in ms).
    self._log.debug('Artifact cache server ping times: {}'
                    .format(', '.join(['{}: {:.6f} secs'.format(*p) for p in pingtimes])))
    argmin = min(range(len(pingtimes)), key=lambda i: pingtimes[i][1])
    best_url = urls[argmin]
    if pingtimes[argmin][1] == Pinger.UNREACHABLE:
      return None  # No reachable artifact caches.
    self._log.debug('Best artifact cache is {0}'.format(best_url))
    return best_url

  def _do_create_artifact_cache(self, spec, action):
    """Returns an artifact cache for the specified spec.

    spec can be:
      - a path to a file-based cache root.
      - a URL of a RESTful cache root.
      - a bar-separated list of URLs, where we'll pick the one with the best ping times.
      - A list or tuple of two specs, local, then remote, each as described above
    """
    if not spec:
      raise EmptyCacheSpecError()
    compression = self._options.compression_level
    if compression not in range(10):
      raise ValueError('compression_level must be an integer 0-9: {}'.format(compression))
    artifact_root = self._options.pants_workdir

    def create_local_cache(parent_path):
      path = os.path.join(parent_path, self._stable_name)
      self._log.debug('{0} {1} local artifact cache at {2}'
                      .format(self._stable_name, action, path))
      return LocalArtifactCache(artifact_root, path, compression)

    def create_remote_cache(urls, local_cache):
      best_url = self.select_best_url(urls)
      if best_url:
        url = best_url.rstrip('/') + '/' + self._stable_name
        self._log.debug('{0} {1} remote artifact cache at {2}'
                        .format(self._stable_name, action, url))
        local_cache = local_cache or TempLocalArtifactCache(artifact_root, compression)
        return RESTfulArtifactCache(artifact_root, url, local_cache)

    def is_local(string_spec):
      return string_spec.startswith('/') or string_spec.startswith('~')

    def is_remote(string_spec):
      return string_spec.startswith('http://') or string_spec.startswith('https://')

    def create_cache_from_string_spec(string_spec):
      if is_remote(string_spec):
        return create_remote_cache(string_spec, TempLocalArtifactCache(artifact_root, compression))
      elif is_local(string_spec):
        return create_local_cache(string_spec)
      else:
        raise CacheSpecFormatError('Invalid artifact cache spec: {0}'.format(string_spec))

    if isinstance(spec, string_types):
      return create_cache_from_string_spec(spec)
    elif isinstance(spec, (list, tuple)):
      if len(spec) == 1:
        return create_cache_from_string_spec(spec[0])
      elif len(spec) == 2:
        if not is_local(spec[0]):
          raise LocalCacheSpecRequiredError(
            'First of two cache specs must be a local cache path. Found: {0}'.format(spec[0]))
        if not is_remote(spec[1]):
          raise RemoteCacheSpecRequiredError(
            'Second of two cache specs must be a remote spec. Found: {0}'.format(spec[1]))
        return create_remote_cache(spec[1], create_local_cache(spec[0]))
    else:
      raise InvalidCacheSpecError('Invalid artifact cache spec type: {0} ({1})'.format(
        type(spec), spec))
