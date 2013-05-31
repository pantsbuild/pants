import httplib
import os
import urlparse
from twitter.common.contextutil import temporary_file_path, open_tar, temporary_file
from twitter.common.quantity import Amount, Data
from twitter.pants.cache.artifact_cache import ArtifactCache


class RESTfulArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts on a RESTful service."""

  READ_SIZE = Amount(4, Data.MB).as_(Data.BYTES)

  def __init__(self, log, artifact_root, url_base, compress=True):
    """
    url_base: The prefix for urls on some RESTful service. We must be able to PUT and GET to any
              path under this base.
    compress: Whether to compress the artifacts before storing them.
    """
    ArtifactCache.__init__(self, log, artifact_root)
    parsed_url = urlparse.urlparse(url_base)
    if parsed_url.scheme == 'http':
      self._ssl = False
    elif parsed_url.scheme == 'https':
      self._ssl = True
    else:
      raise ValueError('RESTfulArtifactCache only supports HTTP and HTTPS')
    self._timeout_secs = 2.0
    self._netloc = parsed_url.netloc
    self._path_prefix = parsed_url.path.rstrip('/')
    self.compress = compress

  def try_insert(self, cache_key, build_artifacts):
    with temporary_file_path() as tarfile:
      mode = 'w:bz2' if self.compress else 'w'
      with open_tar(tarfile, mode, dereference=True) as tarout:
        for artifact in build_artifacts:
          # Adds dirs recursively.
          tarout.add(artifact, os.path.relpath(artifact, self.artifact_root))

      with open(tarfile, 'rb') as infile:
        path = self._path_for_key(cache_key)
        if not self._request('PUT', path, body=infile):
          raise self.CacheError('Failed to PUT to %s. Error: 404' % self._url_string(path))

  def has(self, cache_key):
    return self._request('HEAD', self._path_for_key(cache_key)) is not None

  def use_cached_files(self, cache_key):
    # This implementation fetches the appropriate tarball and extracts it.
    path = self._path_for_key(cache_key)
    try:
      # Send an HTTP request for the tarball.
      response = self._request('GET', path)
      if response is None:
        return False
      expected_size = int(response.getheader('content-length', -1))
      if expected_size == -1:
        raise self.CacheError('No content-length header in HTTP response')

      done = False
      self.log.info('Reading %d bytes from artifact cache at %s' %
                    (expected_size, self._url_string(path)))
      # Read the data in a loop.
      with temporary_file() as outfile:
        total_bytes = 0
        while not done:
          data = response.read(self.READ_SIZE)
          outfile.write(data)
          if len(data) < self.READ_SIZE:
            done = True
          total_bytes += len(data)
          self.log.debug('Read %d bytes' % total_bytes)
        outfile.close()
        # Check the size.
        if total_bytes != expected_size:
          raise self.CacheError('Read only %d bytes from %d expected' % (total_bytes,
                                                                         expected_size))
          # Extract the tarfile.
        mode = 'r:bz2' if self.compress else 'r'
        with open_tar(outfile.name, mode) as tarfile:
          tarfile.extractall(self.artifact_root)
      return True
    except Exception, e:
        self.log.warn('Error while reading from artifact cache: %s' % e)
        return False

  def delete(self, cache_key):
    path = self._path_for_key(cache_key)
    self._request('DELETE', path)

  def _path_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return '%s/%s/%s.tar.bz2' % (self._path_prefix, cache_key.id, cache_key.hash)

  def _connect(self):
    if self._ssl:
      return httplib.HTTPSConnection(self._netloc, timeout=self._timeout_secs)
    else:
      return httplib.HTTPConnection(self._netloc, timeout=self._timeout_secs)

  # Returns a response if we get a 200, None if we get a 404 and raises an exception otherwise.
  def _request(self, method, path, body=None):
    self.log.debug('Sending %s request to %s' % (method, self._url_string(path)))
    # TODO(benjy): Keep connection open and reuse?
    conn = self._connect()
    conn.request(method, path, body=body)
    response = conn.getresponse()
    # TODO: Can HEAD return 204? It would be correct, but I've not seen it happen.
    if response.status == 200:
      return response
    elif response.status == 404:
      return None
    else:
      raise self.CacheError('Failed to %s %s. Error: %d %s' % (method, self._url_string(path),
                                                               response.status, response.reason))

  def _url_string(self, path):
    return '%s://%s%s' % (('https' if self._ssl else 'http'), self._netloc, path)
