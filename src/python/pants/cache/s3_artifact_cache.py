# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

import boto3
from botocore import exceptions
from botocore.config import Config
from botocore.vendored.requests import ConnectionError, Timeout
from botocore.vendored.requests.packages.urllib3.exceptions import ClosedPoolError
from pyjavaproperties import Properties
from six.moves.urllib.parse import urlparse

from pants.cache.artifact_cache import ArtifactCache, NonfatalArtifactCacheError, UnreadableArtifact


logger = logging.getLogger(__name__)

_NETWORK_ERRORS = [
  ConnectionError, Timeout, ClosedPoolError,
  exceptions.EndpointConnectionError, exceptions.ChecksumError
]

def _connect_to_s3(config_file, profile_name):
  # Yeah, I know it's gross but it spams the logs without it:
  boto3.set_stream_logger(name='boto3.resources', level=logging.WARN)
  boto3.set_stream_logger(name='botocore', level=logging.WARN)

  boto_kwargs = {}
  if profile_name:
    boto_kwargs['profile_name'] = profile_name

  try:
    with open(config_file, 'r') as f:
      p = Properties()
      p.load(f)

      access_key = p.get('accessKey')
      if access_key:
        logger.debug('Reading access key from {0}'.format(config_file))
        boto_kwargs['aws_access_key_id'] = access_key

      secret_key = p.get('secretKey')
      if secret_key:
        logger.debug('Reading access key from {0}'.format(config_file))
        boto_kwargs['aws_secret_access_key'] = secret_key
  except IOError:
    logger.debug('Could not load {0}, using ENV vars'.format(config_file))

  session = boto3.Session(**boto_kwargs)
  config = Config(connect_timeout=4, read_timeout=4)
  return session.resource('s3', config=config)


_READ_SIZE_BYTES = 4 * 1024 * 1024


def iter_content(body):
  while True:
    chunk = body.read(_READ_SIZE_BYTES)
    if not chunk:
      break
    yield chunk


def _not_found_error(e):
  if not isinstance(e, exceptions.ClientError):
    return False
  return e.response['Error']['Code'] in ('404', 'NoSuchKey')


def _network_error(e):
  return any(isinstance(e, cls) for cls in _NETWORK_ERRORS)

_NOT_FOUND = 0
_NETWORK = 1
_UNKNOWN = 2


def _log_and_classify_error(e, verb, cache_key):
  if _not_found_error(e):
    logger.debug('Not Found During {0} {1}'.format(verb, cache_key))
    return _NOT_FOUND
  if _network_error(e):
    logger.debug('Failed to {0} (network) {1}: {2}'.format(verb, cache_key, str(e)))
    return _NETWORK
  logger.debug('Failed to {0} (client) {1}: {2}'.format(verb, cache_key, str(e)))
  return _UNKNOWN


class S3ArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts on S3."""

  def __init__(self, config_file, profile_name, artifact_root, s3_url, local):
    """
    :param artifact_root: The path under which cacheable products will be read/written
    :param s3_url: URL of the form s3://bucket/path/to/store/artifacts
    :param BaseLocalArtifactCache local: local cache instance for storing and creating artifacts
    """
    super(S3ArtifactCache, self).__init__(artifact_root)
    url = urlparse(s3_url)
    self._s3 = _connect_to_s3(config_file, profile_name)
    self._path = url.path
    if self._path.startswith('/'):
      self._path = self._path[1:]
    self._localcache = local
    self._bucket = url.netloc

  def try_insert(self, cache_key, paths):
    logger.debug('Insert {0}'.format(cache_key))
    # Delegate creation of artifacts to the local cache
    with self._localcache.insert_paths(cache_key, paths) as tarfile:
      with open(tarfile, 'rb') as infile:
        # Upload artifact to the remote cache.
        try:
          response = self._get_object(cache_key).put(Body=infile)
          response_status = response['ResponseMetadata']['HTTPStatusCode']
          if response_status < 200 or response_status >= 300:
            raise NonfatalArtifactCacheError('Failed to PUT (http error) {0}: {1}'.format(
              cache_key, response_status))
        except Exception as e:
          raise NonfatalArtifactCacheError(
            'Failed to PUT (core error) {0}: {1}'.format(cache_key, str(e)))

  def has(self, cache_key):
    logger.debug('Has {0}'.format(cache_key))
    if self._localcache.has(cache_key):
      return True
    try:
      self._get_object(cache_key).load()
      return True
    except Exception as e:
      _log_and_classify_error(e, 'HEAD', cache_key)
      return False

  def use_cached_files(self, cache_key, results_dir=None):
    logger.debug('GET {0}'.format(cache_key))
    if self._localcache.has(cache_key):
      return self._localcache.use_cached_files(cache_key, results_dir)

    s3_object = self._get_object(cache_key)
    try:
      get_result = s3_object.get()
    except Exception as e:
      _log_and_classify_error(e, 'GET', cache_key)
      return False

    # Delegate storage and extraction to local cache
    body = get_result['Body']
    try:      
      return self._localcache.store_and_use_artifact(
        cache_key, iter_content(body), results_dir)
    except Exception as e:
      result = _log_and_classify_error(e, 'GET', cache_key)
      if result == _UNKNOWN:
        return UnreadableArtifact(cache_key, e)
      return False
    finally:
      body.close()

  def delete(self, cache_key):
    logger.debug("Delete {0}".format(cache_key))
    self._localcache.delete(cache_key)
    try:
      self._get_object(cache_key).delete()
    except Exception as e:
      _log_and_classify_error(e, 'DELETE', cache_key)

  def _get_object(self, cache_key):
    return self._s3.Object(self._bucket, self._path_for_key(cache_key))

  def _path_for_key(self, cache_key):
    return '{0}/{1}/{2}.tgz'.format(self._path, cache_key.id, cache_key.hash)
