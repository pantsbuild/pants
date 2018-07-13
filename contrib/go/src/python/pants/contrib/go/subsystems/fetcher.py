# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from abc import abstractmethod
from collections import namedtuple

from pants.scm.git import Git
from pants.util.meta import AbstractClass

from pants.contrib.go.subsystems.fetch_error import FetchError
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary


logger = logging.getLogger(__name__)


class Fetcher(AbstractClass):
  """Knows how to interpret remote import paths and fetch code to satisfy them."""

  def __init__(self, import_path):
    self._import_path = import_path

  @property
  def import_path(self):
    return self._import_path

  @abstractmethod
  def root(self):
    """Returns the root of this fetcher's remote import_path.

    The root is defined as the portion of the remote import path indicating the associated
    package's remote location; ie: for the remote import path of
    'github.com/docker/docker/daemon/events' it would be 'github.com/docker/docker'.

    Many remote import paths may share the same root; ie: all the 20+ docker packages hosted at
    https://github.com/docker/docker share the 'github.com/docker/docker' root.

    This is called the import-prefix in 'https://golang.org/cmd/go/#hdr-Remote_import_paths'

    :returns: The root portion of the import path.
    :rtype: string
    :raises: :class:`FetchError` if there was a problem detecting the root.
    """

  @abstractmethod
  def fetch(self, dest, rev=None):
    """Fetches the remote library to the given dest dir.

    The dest dir provided will be an existing empty directory.

    :param string dest: The path of an existing empty directory to extract package containing the
                        remote library's contents to.
    :param string rev: The version to fetch - may be `None` or empty indicating the latest version
                       should be fetched.
    :raises: :class:`FetchError` if there was a problem fetching the remote package.
    """


class CloningFetcher(Fetcher):
  """A fetcher that gets the remote library by cloning its repo.

  This emulates the standard way go fetch works, and follows the protocol described here:
  https://golang.org/cmd/go/#hdr-Remote_import_paths. In particular, it inspects go-import
  meta tags.

  Not that currently we require meta tags, and don't support the explicit form:
  import "example.org/repo.git/foo/bar", as it looks like it's not used much in practice.
  """
  # TODO: Support the explicit form if needed. It wouldn't be difficult.

  def __init__(self, import_path, meta_tag_reader):
    super(CloningFetcher, self).__init__(import_path)
    self._meta_tag_reader = meta_tag_reader

  def root(self):
    imported_repo = self._meta_tag_reader.get_imported_repo(self.import_path)
    if imported_repo:
      return imported_repo.import_prefix
    else:
      raise FetchError('No <meta name="go-import"> tag found at {}'.format(self.import_path))

  def fetch(self, dest, rev=None):
    imported_repo = self._meta_tag_reader.get_imported_repo(self.import_path)
    if not imported_repo:
      raise FetchError('No <meta name="go-import"> tag found, so cannot fetch repo '
                       'at {}'.format(self.import_path))
    if imported_repo.vcs != 'git':
      # TODO: Support other vcs systems as needed.
      raise FetchError("Don't know how to fetch for vcs type {}.".format(imported_repo.vcs))
    # TODO: Do this in a workunit (see https://github.com/pantsbuild/pants/issues/3502).
    logger.info('Cloning {} into {}'.format(imported_repo.url, dest))
    repo = Git.clone(imported_repo.url, dest)
    if rev:
      repo.set_state(rev)


class ArchiveFetcher(Fetcher):
  """A fetcher that retrieves and unpacks remote libraries from archive files."""

  class UrlInfo(namedtuple('UrlInfo', ['url_format', 'default_rev', 'strip_level'])):
    """Information about a remote archive.

    - url_format: A string template that yields the remote archive's url when formatted with the
                  remote import path\'s `rev`, `import_prefix`, and `pkg`.
    - default_rev: Fetch this rev if no other rev is specified.
    - strip_level: An integer indicating the number of leading path components to strip from
                   files upacked from the archive.
    """

  def __init__(self, import_path, import_prefix, url_info, archive_retriever):
    super(ArchiveFetcher, self).__init__(import_path)
    self._import_prefix = import_prefix
    self._url_info = url_info
    self._archive_retriver = archive_retriever

  def root(self):
    return self._import_prefix

  def fetch(self, dest, rev=None):
    pkg = GoRemoteLibrary.remote_package_path(self.root(), self.import_path)
    archive_url = self._url_info.url_format.format(rev=rev or self._url_info.default_rev,
                                                   pkg=pkg, import_prefix=self.root())
    try:
      self._fetch(archive_url, self._url_info.strip_level, dest)
    except FetchError as e:
      # Modify the message to add more information, then reraise with the original traceback.
      e.add_message_prefix('Error while fetching import {}: '.format(self.import_path))
      raise

  def _fetch(self, archive_url, strip_level, dest):
    # Note: Broken out into a separate function so we can mock it out easily in tests.
    self._archive_retriver.fetch_archive(archive_url, strip_level, dest)
