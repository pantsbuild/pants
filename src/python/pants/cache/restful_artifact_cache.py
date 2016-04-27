# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

import requests
from requests import RequestException

from pants.cache.artifact_cache import ArtifactCache, NonfatalArtifactCacheError, UnreadableArtifact


logger = logging.getLogger(__name__)

# Reduce the somewhat verbose logging of requests.
# TODO do this in a central place
logging.getLogger('requests').setLevel(logging.WARNING)


class RequestsSession(object):
  _session = None

  @classmethod
  def instance(cls):
    if cls._session is None:
      cls._session = requests.Session()
    return cls._session


class RESTfulArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts on a RESTful service."""

  READ_SIZE_BYTES = 4 * 1024 * 1024

  def __init__(self, artifact_root, best_url_selector, local):
    """
    :param string artifact_root: The path under which cacheable products will be read/written.
    :param BestUrlSelector best_url_selector: Url selector that supports fail-over. Each returned
      url represents prefix for some RESTful service. We must be able to PUT and GET to any path
      under this base.
    :param BaseLocalArtifactCache local: local cache instance for storing and creating artifacts
    """
    super(RESTfulArtifactCache, self).__init__(artifact_root)

    self.best_url_selector = best_url_selector
    self._timeout_secs = 4.0
    self._localcache = local

  def try_insert(self, cache_key, paths):
    # Delegate creation of artifact to local cache.
    with self._localcache.insert_paths(cache_key, paths) as tarfile:
      # Upload local artifact to remote cache.
      with open(tarfile, 'rb') as infile:
        if not self._request('PUT', cache_key, body=infile):
          raise NonfatalArtifactCacheError('Failed to PUT {0}.'.format(cache_key))

  def has(self, cache_key):
    if self._localcache.has(cache_key):
      return True
    return self._request('HEAD', cache_key) is not None

  def use_cached_files(self, cache_key, results_dir=None):
    if self._localcache.has(cache_key):
      return self._localcache.use_cached_files(cache_key, results_dir)

    try:
      response = self._request('GET', cache_key)
      if response is not None:
        # Delegate storage and extraction to local cache
        byte_iter = response.iter_content(self.READ_SIZE_BYTES)
        return self._localcache.store_and_use_artifact(cache_key, byte_iter, results_dir)
    except Exception as e:
      logger.warn('\nError while reading from remote artifact cache: {0}\n'.format(e))
      # TODO(peiyu): clean up partially downloaded local file if any
      return UnreadableArtifact(cache_key, e)

    return False

  def delete(self, cache_key):
    self._localcache.delete(cache_key)
    self._request('DELETE', cache_key)

  # Returns a response if we get a 200, None if we get a 404 and raises an exception otherwise.
  def _request(self, method, cache_key, body=None):

    session = RequestsSession.instance()
    with self.best_url_selector.select_best_url() as best_url:
      url = self._url_for_key(best_url, cache_key)
      logger.debug('Sending {0} request to {1}'.format(method, url))
      try:
        if 'PUT' == method:
          response = session.put(url, data=body, timeout=self._timeout_secs)
        elif 'GET' == method:
          response = session.get(url, timeout=self._timeout_secs, stream=True)
        elif 'HEAD' == method:
          response = session.head(url, timeout=self._timeout_secs)
        elif 'DELETE' == method:
          response = session.delete(url, timeout=self._timeout_secs)
        else:
          raise ValueError('Unknown request method {0}'.format(method))
      except RequestException as e:
        raise NonfatalArtifactCacheError('Failed to {0} {1}. Error: {2}'
                                         .format(method, url, e))
      # Allow all 2XX responses. E.g., nginx returns 201 on PUT. HEAD may return 204.
      if int(response.status_code / 100) == 2:
        return response
      elif response.status_code == 404:
        logger.debug('404 returned for {0} request to {1}'.format(method, url))
        return None
      else:
        raise NonfatalArtifactCacheError('Failed to {0} {1}. Error: {2} {3}'
                                         .format(method, url,
                                                 response.status_code, response.reason))

  def _url_for_key(self, url, cache_key):
    path_prefix = url.path.rstrip(b'/')
    path = '{0}/{1}/{2}.tgz'.format(path_prefix, cache_key.id, cache_key.hash)
    return '{0}://{1}{2}'.format(url.scheme, url.netloc, path)
