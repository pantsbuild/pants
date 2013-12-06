import httplib
import urlparse
from twitter.common.contextutil import temporary_file_path, temporary_file
from twitter.common.quantity import Amount, Data
from twitter.pants.cache.artifact import TarballArtifact
from twitter.pants.cache.artifact_cache import ArtifactCache


class RESTfulArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts on a RESTful service."""

  READ_SIZE = int(Amount(4, Data.MB).as_(Data.BYTES))

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
    self._timeout_secs = 4.0
    self._netloc = parsed_url.netloc
    self._path_prefix = parsed_url.path.rstrip('/')
    self.compress = compress

  def try_insert(self, cache_key, paths):
    with temporary_file_path() as tarfile:
      artifact = TarballArtifact(self.artifact_root, tarfile, self.compress)
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

      done = False
      with temporary_file() as outfile:
        total_bytes = 0
        # Read the data in a loop.
        while not done:
          data = response.read(self.READ_SIZE)
          outfile.write(data)
          if len(data) < self.READ_SIZE:
            done = True
          total_bytes += len(data)
        outfile.close()
        self.log.debug('Read %d bytes from artifact cache at %s' %
                       (total_bytes,self._url_string(remote_path)))

        # Extract the tarfile.
        artifact = TarballArtifact(self.artifact_root, outfile.name, self.compress)
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
                               '.tar.gz' if self.compress else '.tar')

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
    # Allow all 2XX responses. E.g., nginx returns 201 on PUT. HEAD may return 204.
    if int(response.status / 100) == 2:
      return response
    elif response.status == 404:
      return None
    else:
      raise self.CacheError('Failed to %s %s. Error: %d %s' % (method, self._url_string(path),
                                                               response.status, response.reason))

  def _url_string(self, path):
    return '%s://%s%s' % (('https' if self._ssl else 'http'), self._netloc, path)
