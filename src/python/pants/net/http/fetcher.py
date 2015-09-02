# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import sys
import tempfile
import time
from contextlib import closing, contextmanager

import requests
import six

from pants.util.dirutil import safe_open


class Fetcher(object):
  """A streaming URL fetcher that supports listeners."""

  class Error(Exception):
    """Indicates an error fetching an URL."""

  class TransientError(Error):
    """Indicates a fetch error for an operation that may reasonably be retried.

    For example a connection error or fetch timeout are both considered transient.
    """

  class PermanentError(Error):
    """Indicates a fetch error that is likely permanent.

    Retrying operations that raise these errors is unlikely to succeed.  For example, an HTTP 404
    response code is considered a permanent error.
    """

    def __init__(self, value=None, response_code=None):
      super(Fetcher.PermanentError, self).__init__(value)
      if response_code and not isinstance(response_code, six.integer_types):
        raise ValueError('response_code must be an integer, got {}'.format(response_code))
      self._response_code = response_code

    @property
    def response_code(self):
      """The HTTP response code of the failed request.

      May be None it the request failed before receiving a server response.
      """
      return self._response_code

  _TRANSIENT_EXCEPTION_TYPES = (requests.ConnectionError, requests.Timeout)

  class Listener(object):
    """A listener callback interface for HTTP GET requests made by a Fetcher."""

    def status(self, code, content_length=None):
      """Called when the response headers are received before data starts streaming.

      :param int code: the HTTP response code
      :param int content_length: the response Content-Length if known, otherwise None
      """

    def recv_chunk(self, data):
      """Called as each chunk of data is received from the streaming response.

      :param data: a byte string containing the next chunk of response data
      """

    def finished(self):
      """Called when the response has been fully read."""

    def wrap(self, listener=None):
      """Returns a Listener that wraps both the given listener and this listener, calling each in
      turn for each callback method.
      """
      if not listener:
        return self

      class Wrapper(Fetcher.Listener):
        def status(wrapper, code, content_length=None):
          listener.status(code, content_length=content_length)
          self.status(code, content_length=content_length)

        def recv_chunk(wrapper, data):
          listener.recv_chunk(data)
          self.recv_chunk(data)

        def finished(wrapper):
          listener.finished()
          self.finished()

      return Wrapper()

  class DownloadListener(Listener):
    """A Listener that writes all received data to a file like object."""

    def __init__(self, fh):
      """Creates a DownloadListener that writes to the given open file handle.

      The file handle is not closed.

      :param fh: a file handle open for writing
      """
      if not fh or not hasattr(fh, 'write'):
        raise ValueError('fh must be an open file handle, given {}'.format(fh))
      self._fh = fh

    def recv_chunk(self, data):
      self._fh.write(data)

  class ChecksumListener(Listener):
    """A Listener that checksums the data received."""

    def __init__(self, digest=None):
      """Creates a ChecksumListener with the given hashlib digest or else an MD5 digest if none is
      supplied.

      :param digest: the digest to use to checksum the received data, MDS by default
      """
      self.digest = digest or hashlib.md5()
      self._checksum = None

    def recv_chunk(self, data):
      self.digest.update(data)

    def finished(self):
      self._checksum = self.digest.hexdigest()

    @property
    def checksum(self):
      """Returns the hex digest of the received data.

      Its not valid to access this property before the listener is finished.

      :rtype: string
      :raises: ValueError if accessed before this listener is finished
      """
      if self._checksum is None:
        raise ValueError('The checksum cannot be accessed before this listener is finished.')
      return self._checksum

  class ProgressListener(Listener):
    """A Listener that logs progress to stdout."""

    def __init__(self, width=None, chunk_size_bytes=None):
      """Creates a ProgressListener that logs progress for known size items with a progress bar of
      the given width in characters and otherwise logs a progress indicator every chunk_size.

      :param int width: the width of the progress bar for known size downloads, 50 by default.
      :param chunk_size_bytes: The size of data chunks to note progress for, 10 KB by default.
      """
      self._width = width or 50
      if not isinstance(self._width, six.integer_types):
        raise ValueError('The width must be an integer, given {}'.format(self._width))
      self._chunk_size_bytes = chunk_size_bytes or 10 * 1024
      self._start = time.time()

    def status(self, code, content_length=None):
      self.size = content_length

      if content_length:
        self.download_size = int(content_length / 1024)
        self.chunk_size = content_length / self._width
      else:
        self.chunk_size = self._chunk_size_bytes

      self.chunks = 0
      self.read = 0

    def recv_chunk(self, data):
      self.read += len(data)
      chunk_count = int(self.read / self.chunk_size)
      if chunk_count > self.chunks:
        self.chunks = chunk_count
        if self.size:
          sys.stdout.write('\r')
          sys.stdout.write('{:3}% '.format(int(self.read * 1.0 / self.size) * 100))
        sys.stdout.write('.' * self.chunks)
        if self.size:
          size_width = len(str(self.download_size))
          downloaded = int(self.read / 1024)
          sys.stdout.write('{} {} KB'.format(' ' * (self._width - self.chunks),
                                         str(downloaded).rjust(size_width)))
        sys.stdout.flush()

    def finished(self):
      if self.chunks > 0:
        sys.stdout.write(' {:.3f}s\n'.format(time.time() - self._start))
        sys.stdout.flush()

  def __init__(self, requests_api=None):
    """Creates a Fetcher that uses the given requests api object.

    By default uses the requests module, but can be any object conforming to the requests api like
    a requests Session object.
    """
    self._requests = requests_api or requests

  def fetch(self, url, listener, chunk_size_bytes=None, timeout_secs=None):
    """Fetches data from the given URL notifying listener of all lifecycle events.

    :param string url: the url to GET data from
    :param listener: the listener to notify of all download lifecycle events
    :param chunk_size_bytes: the chunk size to use for buffering data, 10 KB by default
    :param timeout_secs: the maximum time to wait for data to be available, 1 second by default
    :raises: Fetcher.Error if there was a problem fetching all data from the given url
    """
    chunk_size_bytes = chunk_size_bytes or 10 * 1024
    timeout_secs = timeout_secs or 1.0

    if not isinstance(listener, self.Listener):
      raise ValueError('listener must be a Listener instance, given {}'.format(listener))

    try:
      with closing(self._requests.get(url, stream=True, timeout=timeout_secs)) as resp:
        if resp.status_code != requests.codes.ok:
          listener.status(resp.status_code)
          raise self.PermanentError('GET request to {} failed with status code {}'
                                    .format(url, resp.status_code),
                                    response_code=resp.status_code)

        size = resp.headers.get('content-length')
        listener.status(resp.status_code, content_length=int(size) if size else None)

        read_bytes = 0
        for data in resp.iter_content(chunk_size=chunk_size_bytes):
          listener.recv_chunk(data)
          read_bytes += len(data)
        if size and read_bytes != int(size):
          raise self.Error('Expected {} bytes, read {}'.format(size, read_bytes))
        listener.finished()
    except requests.RequestException as e:
      exception_factory = (self.TransientError if isinstance(e, self._TRANSIENT_EXCEPTION_TYPES)
                           else self.PermanentError)
      raise exception_factory('Problem GETing data from {}: {}'.format(url, e))

  def download(self, url, listener=None, path_or_fd=None, chunk_size_bytes=None, timeout_secs=None):
    """Downloads data from the given URL.

    By default data is downloaded to a temporary file.

    :param string url: the url to GET data from
    :param listener: an optional listener to notify of all download lifecycle events
    :param path_or_fd: an optional file path or open file descriptor to write data to
    :param chunk_size_bytes: the chunk size to use for buffering data
    :param timeout_secs: the maximum time to wait for data to be available
    :returns: the path to the file data was downloaded to.
    :raises: Fetcher.Error if there was a problem downloading all data from the given url.
    """
    @contextmanager
    def download_fp(_path_or_fd):
      if _path_or_fd and not isinstance(_path_or_fd, six.string_types):
        yield _path_or_fd, _path_or_fd.name
      else:
        if not _path_or_fd:
          fd, _path_or_fd = tempfile.mkstemp()
          os.close(fd)
        with safe_open(_path_or_fd, 'w') as fp:
          yield fp, _path_or_fd

    with download_fp(path_or_fd) as (fp, path):
      listener = self.DownloadListener(fp).wrap(listener)
      self.fetch(url, listener, chunk_size_bytes=chunk_size_bytes, timeout_secs=timeout_secs)
      return path
