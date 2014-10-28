# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import urlparse

import requests
from requests import RequestException

from pants.cache.artifact import TarballArtifact
from pants.cache.artifact_cache import ArtifactCache
from pants.util.contextutil import temporary_file, temporary_file_path


# Reduce the somewhat verbose logging of requests.
# TODO do this in a central place
logging.getLogger('requests').setLevel(logging.WARNING)

class RESTfulArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts on a RESTful service."""

  READ_SIZE_BYTES = 4 * 1024 * 1024

  def __init__(self, log, artifact_root, url_base, compression):
    """
    url_base: The prefix for urls on some RESTful service. We must be able to PUT and GET to any
              path under this base.
    :param int compression: compression level (of false-y to skip compression) for artifacts
    """
    ArtifactCache.__init__(self, log, artifact_root)
    parsed_url = urlparse.urlparse(url_base)
    if parsed_url.scheme == 'http':
      self._ssl = False
    elif parsed_url.scheme == 'https':
      self._ssl = True
    else:
      raise ValueError('RESTfulArtifactCache only supports HTTP and HTTPS')
    self._timeout_secs = 4.0
    self._netloc = parsed_url.netloc
    self._path_prefix = parsed_url.path.rstrip(b'/')
    self.compression = compression

    # To enable connection reuse, all requests must be created from same session.
    # TODO: Re-evaluate session's life-cycle if/when a longer-lived pants process exists.
    self._session = requests.Session()


  def try_insert(self, cache_key, paths):
    with temporary_file_path() as tarfile:
      artifact = TarballArtifact(self.artifact_root, tarfile, self.compression)
      artifact.collect(paths)

      with open(tarfile, 'rb') as infile:
        remote_path = self._remote_path_for_key(cache_key)
        if not self._request('PUT', remote_path, body=infile):
          raise self.CacheError('Failed to PUT to %s. Error: 404' % self._url_string(remote_path))

  def has(self, cache_key):
    return self._request('HEAD', self._remote_path_for_key(cache_key)) is not None

  def use_cached_files(self, cache_key):
    # This implementation fetches the appropriate tarball and extracts it.
    remote_path = self._remote_path_for_key(cache_key)
    try:
      # Send an HTTP request for the tarball.
      response = self._request('GET', remote_path)
      if response is None:
        return None

      with temporary_file() as outfile:
        total_bytes = 0
        # Read the data in a loop.
        for chunk in response.iter_content(self.READ_SIZE_BYTES):
          outfile.write(chunk)
          total_bytes += len(chunk)

        outfile.close()
        self.log.debug('Read %d bytes from artifact cache at %s' %
                       (total_bytes,self._url_string(remote_path)))

        # Extract the tarfile.
        artifact = TarballArtifact(self.artifact_root, outfile.name, self.compression)
        artifact.extract()
        return artifact
    except Exception as e:
      self.log.warn('Error while reading from remote artifact cache: %s' % e)
      return None

  def delete(self, cache_key):
    remote_path = self._remote_path_for_key(cache_key)
    self._request('DELETE', remote_path)

  def prune(self, age_hours):
    # Doesn't make sense for a client to prune a remote server.
    # Better to run tmpwatch on the server.
    pass

  def _remote_path_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return '%s/%s/%s%s' % (self._path_prefix, cache_key.id, cache_key.hash,
                           '.tar.gz' if self.compression else '.tar')

  # Returns a response if we get a 200, None if we get a 404 and raises an exception otherwise.
  def _request(self, method, path, body=None):
    url = self._url_string(path)
    self.log.debug('Sending %s request to %s' % (method, url))

    try:
      response = None
      if 'PUT' == method:
        response = self._session.put(url, data=body, timeout=self._timeout_secs)
      elif 'GET' == method:
        response = self._session.get(url, timeout=self._timeout_secs, stream=True)
      elif 'HEAD' == method:
        response = self._session.head(url, timeout=self._timeout_secs)
      elif 'DELETE' == method:
        response = self._session.delete(url, timeout=self._timeout_secs)
      else:
        raise ValueError('Unknown request method %s' % method)

      # Allow all 2XX responses. E.g., nginx returns 201 on PUT. HEAD may return 204.
      if int(response.status_code / 100) == 2:
        return response
      elif response.status_code == 404:
        self.log.debug('404 returned for %s request to %s' % (method, self._url_string(path)))
        return None
      else:
        raise self.CacheError('Failed to %s %s. Error: %d %s' % (method, self._url_string(path),
                                                                 response.status_code, response.reason))
    except RequestException as e:
      raise self.CacheError(e)

  def _url_string(self, path):
    return '%s://%s%s' % (('https' if self._ssl else 'http'), self._netloc, path)
