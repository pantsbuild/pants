# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import re

from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property

from pants.contrib.go.subsystems.archive_retriever import ArchiveRetriever
from pants.contrib.go.subsystems.fetch_error import FetchError
from pants.contrib.go.subsystems.fetcher import ArchiveFetcher, CloningFetcher
from pants.contrib.go.subsystems.go_import_meta_tag_reader import GoImportMetaTagReader


logger = logging.getLogger(__name__)


class FetcherFactory(Subsystem):
  """A fetcher that retrieves and unpacks remote libraries from archive files."""

  options_scope = 'go-fetchers'

  @classmethod
  def subsystem_dependencies(cls):
    return (super(FetcherFactory, cls).subsystem_dependencies() +
            (ArchiveRetriever, GoImportMetaTagReader))

  _DEFAULT_MATCHERS = {
    # TODO: Add launchpad.net?
    r'bitbucket\.org/(?P<user>[^/]+)/(?P<repo>[^/]+)':
      ArchiveFetcher.UrlInfo(
          url_format='https://bitbucket.org/\g<user>/\g<repo>/get/{rev}.tar.gz',
          default_rev='tip',
          strip_level=1),
    r'github\.com/(?P<user>[^/]+)/(?P<repo>[^/]+)':
      ArchiveFetcher.UrlInfo(
          url_format='https://github.com/\g<user>/\g<repo>/archive/{rev}.tar.gz',
          default_rev='master',
          strip_level=1),
  }

  @classmethod
  def register_options(cls, register):
    super(FetcherFactory, cls).register_options(register)
    register('--disallow-cloning-fetcher', type=bool, default=False, advanced=True,
             help="If True, we only fetch archives explicitly matched by --matchers."
                  "Otherwise we fall back to cloning the remote repos, using Go's standard "
                  "remote dependency resolution protocol.")
    register('--matchers', metavar='<mapping>', type=dict,
             default=cls._DEFAULT_MATCHERS, advanced=True,
             help="A mapping from a remote import path matching regex to an UrlInfo struct "
                  "describing how to fetch and unpack an archive of that remote import path.  "
                  "The regex must match the beginning of the remote import path (no '^' anchor is "
                  "needed, it is assumed) until the first path element that is contained in the "
                  "archive. (e.g. for 'bazil.org/fuse/fs', which lives in the archive of "
                  "'bazil.org/fuse', it must match 'bazil.org/fuse'.)\n"
                  "\n"
                  "The UrlInfo struct is a 3-tuple with the following slots:\n"
                  "0. An url format string that is supplied to the regex match\'s `.expand` "
                  "method and then formatted with the remote import path\'s `rev`, "
                  "`import_prefix`, and `pkg`.\n"
                  "1. The default revision string to use when no `rev` is supplied; ie 'HEAD' or "
                  "'master' for git.\n"
                  "2. An integer indicating the number of leading path components to strip from "
                  "files upacked from the archive.")
    register('--prefixes', metavar='<paths>', type=list, advanced=True,
             fromfile=True, default=[],
             removal_version='1.2.0',
             removal_hint='Remove this option from pants.ini.  It does nothing now.',
             help="Does nothing.")

  def get_fetcher(self, import_path):
    for matcher, unexpanded_url_info in self._matchers:
      # Note that the url_formats are filled in in two stages. We match.expand them here,
      # and the ArchiveFetcher applies .format() later, when it knows the rev.
      match = matcher.match(import_path)
      if match:
        expanded_url_info = ArchiveFetcher.UrlInfo(match.expand(unexpanded_url_info.url_format),
                                                   unexpanded_url_info.default_rev,
                                                   unexpanded_url_info.strip_level)
        return ArchiveFetcher(import_path, match.group(0), expanded_url_info,
                              ArchiveRetriever.global_instance())
    if self.get_options().disallow_cloning_fetcher:
      raise FetchError('Cannot fetch {}. No archive match, and remote repo cloning '
                       'disallowed.'.format(import_path))
    return CloningFetcher(import_path, GoImportMetaTagReader.global_instance())

  @memoized_property
  def _matchers(self):
    matchers = []
    for regex, info in self.get_options().matchers.items():
      matcher = re.compile(regex)
      unexpanded_url_info = ArchiveFetcher.UrlInfo(*info)
      matchers.append((matcher, unexpanded_url_info))
    return matchers
