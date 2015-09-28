# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import urlparse

import requests
from requests import RequestException

from pants.cache.artifact_cache import (ArtifactCache, ArtifactCacheError,
                                        NonfatalArtifactCacheError, UnreadableArtifact)


logger = logging.getLogger(__name__)

# Reduce the somewhat verbose logging of requests.
# TODO do this in a central place
logging.getLogger('requests').setLevel(logging.WARNING)


class InvalidRESTfulCacheProtoError(ArtifactCacheError):
  """Indicates an invalid protocol used in a remote spec."""
  pass


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

  def __init__(self, artifact_root, url_base, local):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    :param str url_base: The prefix for urls on some RESTful service. We must be able to PUT and
                         GET to any path under this base.
    :param BaseLocalArtifactCache local: local cache instance for storing and creating artifacts
    """
    super(RESTfulArtifactCache, self).__init__(artifact_root)
    parsed_url = urlparse.urlparse(url_base)
    if parsed_url.scheme == 'http':
      self._ssl = False
    elif parsed_url.scheme == 'https':
      self._ssl = True
    else:
      raise InvalidRESTfulCacheProtoError(
        'RESTfulArtifactCache only supports HTTP(S). Found: {0}'.format(parsed_url.scheme))
    self._timeout_secs = 4.0
    self._netloc = parsed_url.netloc
    self._path_prefix = parsed_url.path.rstrip(b'/')
    self._localcache = local

  def try_insert(self, cache_key, paths):
    # Delegate creation of artifact to local cache.
    with self._localcache.insert_paths(cache_key, paths) as tarfile:
      # Upload local artifact to remote cache.
      with open(tarfile, 'rb') as infile:
        remote_path = self._remote_path_for_key(cache_key)
        if not self._request('PUT', remote_path, body=infile):
          url = self._url_string(remote_path)
          raise NonfatalArtifactCacheError('Failed to PUT to {0}.'.format(url))

  def has(self, cache_key):
    if self._localcache.has(cache_key):
      return True
    return self._request('HEAD', self._remote_path_for_key(cache_key)) is not None

  def use_cached_files(self, cache_key, hit_callback=None):
    if self._localcache.has(cache_key):
      return self._localcache.use_cached_files(cache_key, hit_callback)

    remote_path = self._remote_path_for_key(cache_key)
    try:
      response = self._request('GET', remote_path)
      if response is not None:
        # Delegate storage and extraction to local cache
        byte_iter = response.iter_content(self.READ_SIZE_BYTES)
        return self._localcache.store_and_use_artifact(cache_key, byte_iter, hit_callback)
    except Exception as e:
      logger.warn('\nError while reading from remote artifact cache: {0}\n'.format(e))
      return UnreadableArtifact(cache_key, e)

    return False

  def delete(self, cache_key):
    self._localcache.delete(cache_key)
    remote_path = self._remote_path_for_key(cache_key)
    self._request('DELETE', remote_path)

  def _remote_path_for_key(self, cache_key):
    return '{0}/{1}/{2}.tgz'.format(self._path_prefix, cache_key.id, cache_key.hash)

  # Returns a response if we get a 200, None if we get a 404 and raises an exception otherwise.
  def _request(self, method, path, body=None):
    url = self._url_string(path)
    logger.debug('Sending {0} request to {1}'.format(method, url))

    session = RequestsSession.instance()

    try:
      response = None
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

      # Allow all 2XX responses. E.g., nginx returns 201 on PUT. HEAD may return 204.
      if int(response.status_code / 100) == 2:
        return response
      elif response.status_code == 404:
        logger.debug('404 returned for {0} request to {1}'.format(method, self._url_string(path)))
        return None
      else:
        raise NonfatalArtifactCacheError('Failed to {0} {1}. Error: {2} {3}'.format(method,
                                                                         self._url_string(path),
                                                                         response.status_code,
                                                                         response.reason))
    except RequestException as e:
      raise NonfatalArtifactCacheError(e)

  def _url_string(self, path):
    proto = 'http'
    if self._ssl:
      proto = 'https'
    return '{0}://{1}{2}'.format(proto, self._netloc, path)
