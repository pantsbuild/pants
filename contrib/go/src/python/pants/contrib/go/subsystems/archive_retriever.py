# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
from contextlib import closing, contextmanager

import requests
from pants.fs.archive import archiver_for_path
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir, temporary_file
from six.moves.urllib.parse import urlparse

from pants.contrib.go.subsystems.fetch_error import FetchError


logger = logging.getLogger(__name__)


class ArchiveRetriever(Subsystem):
  """Retrieves and unpacks remote libraries from archives."""

  options_scope = 'go-archive-retriever'

  @classmethod
  def register_options(cls, register):
    super(ArchiveRetriever, cls).register_options(register)
    register('--buffer-size', metavar='<bytes>', type=int, advanced=True,
             default=10 * 1024,  # 10KB in case jumbo frames are in play.
             help='The number of bytes of archive content to buffer in memory before flushing to '
                  'disk when downloading an archive.')
    register('--retries', type=int, default=1, advanced=True,
             help='How many times to retry when fetching a remote archive.')

  def fetch_archive(self, archive_url, strip_level, dest):
    try:
      archiver = archiver_for_path(archive_url)
    except ValueError:
      raise FetchError("Don't know how to unpack archive at url {}".format(archive_url))

    with self._fetch(archive_url) as archive:
      if strip_level == 0:
        archiver.extract(archive, dest)
      else:
        with temporary_dir() as scratch:
          archiver.extract(archive, scratch)
          for dirpath, dirnames, filenames in os.walk(scratch, topdown=True):
            if dirpath != scratch:
              relpath = os.path.relpath(dirpath, scratch)
              relpath_components = relpath.split(os.sep)
              if len(relpath_components) == strip_level and (dirnames or filenames):
                for path in dirnames + filenames:
                  src = os.path.join(dirpath, path)
                  dst = os.path.join(dest, path)
                  shutil.move(src, dst)
                del dirnames[:]  # Stops the walk.

  @contextmanager
  def _fetch(self, url):
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme == 'file':
      yield parsed.path
    else:
      with self._download(url) as download_path:
        yield download_path

  @contextmanager
  def _download(self, url):
    # TODO(jsirois): Wrap with workunits, progress meters, checksums.
    logger.info('Downloading {}...'.format(url))
    with closing(self._session().get(url, stream=True)) as res:
      if res.status_code != requests.codes.ok:
        raise FetchError('Failed to download {} ({} error)'.format(url, res.status_code))
      with temporary_file() as archive_fp:
        # NB: Archives might be very large so we play it safe and buffer them to disk instead of
        # memory before unpacking.
        for chunk in res.iter_content(chunk_size=self.get_options().buffer_size):
          archive_fp.write(chunk)
        archive_fp.close()
        res.close()
        yield archive_fp.name

  def _session(self):
    session = requests.session()
    # Override default http adapters with a retriable one.
    retriable_http_adapter = requests.adapters.HTTPAdapter(max_retries=self.get_options().retries)
    session.mount("http://", retriable_http_adapter)
    session.mount("https://", retriable_http_adapter)
    return session
