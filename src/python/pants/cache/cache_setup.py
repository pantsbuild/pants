# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import threading
import urlparse
from collections import namedtuple

from six.moves import range

from pants.cache.artifact_cache import ArtifactCacheError
from pants.cache.local_artifact_cache import LocalArtifactCache, TempLocalArtifactCache
from pants.cache.pinger import Pinger
from pants.cache.resolver import NoopResolver, Resolver, RESTfulResolver
from pants.cache.restful_artifact_cache import RESTfulArtifactCache
from pants.option.custom_types import list_option
from pants.subsystem.subsystem import Subsystem


class EmptyCacheSpecError(ArtifactCacheError): pass


class LocalCacheSpecRequiredError(ArtifactCacheError): pass


class CacheSpecFormatError(ArtifactCacheError): pass


class InvalidCacheSpecError(ArtifactCacheError): pass


class RemoteCacheSpecRequiredError(ArtifactCacheError): pass


class TooManyCacheSpecsError(ArtifactCacheError): pass


CacheSpec = namedtuple('CacheSpec', ['local', 'remote'])


class CacheSetup(Subsystem):
  options_scope = 'cache'

  @classmethod
  def register_options(cls, register):
    super(CacheSetup, cls).register_options(register)
    register('--read', action='store_true', default=True,
             help='Read build artifacts from cache, if available.')
    register('--write', action='store_true', default=True,
             help='Write build artifacts to cache, if available.')
    register('--overwrite', advanced=True, action='store_true',
             help='If writing build artifacts to cache, overwrite existing artifacts '
                  'instead of skipping them.')
    register('--resolver', advanced=True, choices=['none', 'rest'], default='none',
             help='Select which resolver strategy to use for discovering URIs that access '
                  'artifact caches. none: use URIs from static config options, i.e. '
                  '--read-from, --write-to. rest: look up URIs by querying a RESTful '
                  'URL, which is a remote address from --read-from, --write-to.')
    register('--read-from', advanced=True, type=list_option,
             help='The URIs of artifact caches to read directly from. Each entry is a URL of '
                  'a RESTful cache, a path of a filesystem cache, or a pipe-separated list of '
                  'alternate caches to choose from. This list is also used as input to '
                  'the resolver. When resolver is \'none\' list is used as is.')
    register('--write-to', advanced=True, type=list_option,
             help='The URIs of artifact caches to write directly to. Each entry is a URL of'
                  'a RESTful cache, a path of a filesystem cache, or a pipe-separated list of '
                  'alternate caches to choose from. This list is also used as input to '
                  'the resolver. When resolver is \'none\' list is used as is.')
    register('--compression-level', advanced=True, type=int, default=5,
             help='The gzip compression level (0-9) for created artifacts.')
    register('--max-entries-per-target', advanced=True, type=int, default=None,
             help='Maximum number of old cache files to keep per task target pair')

  @classmethod
  def create_cache_factory_for_task(cls, task, pinger=None, resolver=None):
    return CacheFactory(cls.scoped_instance(task).get_options(),
                        task.context.log, task.stable_name(), pinger=pinger, resolver=resolver)


class CacheFactory(object):

  def __init__(self, options, log, stable_name, pinger=None, resolver=None):
    """Create a cache factory from settings.

    :param options: Task's scoped options.
    :param log: Task's context log.
    :param stable_name: Task's stable name.
    :param pinger: Pinger to choose the best remote artifact cache URL.
    :param resolver: Resolver to look up remote artifact cache URLs.
    :return: cache factory.
    """
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

    # resolver is also close but failing to resolve might have broader impact than
    # single ping failure, therefore use a higher timeout with more retries.
    self._resolver = resolver or \
                     (RESTfulResolver(timeout=1.0, tries=3) if self._options.resolver == 'rest' else \
                      NoopResolver())

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
      cache_spec = self._resolve(self._sanitize_cache_spec(self._options.read_from))
      if cache_spec:
        with self._cache_setup_lock:
          self._read_cache = self._do_create_artifact_cache(cache_spec, 'will read from')
    return self._read_cache

  def get_write_cache(self):
    """Returns the write cache for this setup, creating it if necessary.

    Returns None if no read cache is configured.
    """
    if self._options.write_to and not self._write_cache:
      cache_spec = self._resolve(self._sanitize_cache_spec(self._options.write_to))
      if cache_spec:
        with self._cache_setup_lock:
          self._write_cache = self._do_create_artifact_cache(cache_spec, 'will write to')
    return self._write_cache

  # VisibleForTesting
  def _sanitize_cache_spec(self, spec):
    if not isinstance(spec, (list, tuple)):
      raise InvalidCacheSpecError('Invalid artifact cache spec type: {0} ({1})'.format(
        type(spec), spec))

    if not spec:
      raise EmptyCacheSpecError()

    if len(spec) > 2:
      raise TooManyCacheSpecsError('Too many artifact cache specs: ({0})'.format(spec))

    local_specs = [s for s in spec if self.is_local(s)]
    remote_specs = [s for s in spec if self.is_remote(s)]

    if not local_specs and not remote_specs:
      raise CacheSpecFormatError('Invalid cache spec: {0}, must be either local or remote'
                                 .format(spec))

    if len(spec) == 2:
      if not local_specs:
        raise LocalCacheSpecRequiredError('One of two cache specs must be a local cache path.')
      if not remote_specs:
        raise RemoteCacheSpecRequiredError('One of two cache specs must be a remote spec.')

    local_spec = local_specs[0] if len(local_specs) > 0 else None
    remote_spec = remote_specs[0] if len(remote_specs) > 0 else None

    return CacheSpec(local=local_spec, remote=remote_spec)

  # VisibleForTesting
  def _resolve(self, spec):
    """Attempt resolving cache URIs when a remote spec is provided. """
    if not spec.remote:
      return spec

    try:
      resolved_urls = self._resolver.resolve(spec.remote)
      if resolved_urls:
        # keep the bar separated list of URLs convention
        return CacheSpec(local=spec.local, remote='|'.join(resolved_urls))
      # no-op
      return spec
    except Resolver.ResolverError as e:
      self._log.warn('Error while resolving from {0}: {1}'.format(spec.remote, str(e)))
      # If for some reason resolver fails we continue to use local cache
      if spec.local:
        return CacheSpec(local=spec.local, remote=None)
      # resolver fails but there is no local cache
      return None

  @staticmethod
  def is_local(string_spec):
    return string_spec.startswith('/') or string_spec.startswith('~')

  @staticmethod
  def is_remote(string_spec):
    # both artifact cache and resolver use REST, add new protocols here once they are supported
    return string_spec.startswith('http://') or string_spec.startswith('https://')

  def select_best_url(self, remote_spec):
    urls = remote_spec.split('|')
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
    compression = self._options.compression_level
    if compression not in range(10):
      raise ValueError('compression_level must be an integer 0-9: {}'.format(compression))
    artifact_root = self._options.pants_workdir

    def create_local_cache(parent_path):
      path = os.path.join(parent_path, self._stable_name)
      self._log.debug('{0} {1} local artifact cache at {2}'
                      .format(self._stable_name, action, path))
      return LocalArtifactCache(artifact_root, path, compression, self._options.max_entries_per_target)

    def create_remote_cache(urls, local_cache):
      best_url = self.select_best_url(urls)
      if best_url:
        url = best_url.rstrip('/') + '/' + self._stable_name
        self._log.debug('{0} {1} remote artifact cache at {2}'
                        .format(self._stable_name, action, url))
        local_cache = local_cache or TempLocalArtifactCache(artifact_root, compression)
        return RESTfulArtifactCache(artifact_root, url, local_cache)

    def create_cache_from_string_spec(string_spec):
      if self.is_remote(string_spec):
        return create_remote_cache(string_spec, TempLocalArtifactCache(artifact_root, compression))
      elif self.is_local(string_spec):
        return create_local_cache(string_spec)
      else:
        raise CacheSpecFormatError('Invalid artifact cache spec: {0}'.format(string_spec))


    local_cache = create_local_cache(spec.local) if spec.local else None
    remote_cache = create_remote_cache(spec.remote, local_cache) if spec.remote else None
    if remote_cache:
      return remote_cache
    return local_cache
