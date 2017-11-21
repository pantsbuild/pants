# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

import requests
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method

from pants.contrib.go.subsystems.imported_repo import ImportedRepo


class GoImportMetaTagReader(Subsystem):
  """Implements a reader for the <meta name="go-import"> protocol.

  See https://golang.org/cmd/go/#hdr-Remote_import_paths .
  """
  options_scope = 'go-import-metatag-reader'

  @classmethod
  def register_options(cls, register):
    super(GoImportMetaTagReader, cls).register_options(register)
    register('--retries', type=int, default=1, advanced=True,
             help='How many times to retry when fetching meta tags.')

  _META_IMPORT_REGEX = re.compile(r"""
      <meta
          \s+
          name=['"]go-import['"]
          \s+
          content=['"](?P<root>[^\s]+)\s+(?P<vcs>[^\s]+)\s+(?P<url>[^\s]+)['"]
          \s*
      >""", flags=re.VERBOSE)

  @classmethod
  def find_meta_tags(cls, page_html):
    """Returns the content of the meta tag if found inside of the provided HTML."""

    return cls._META_IMPORT_REGEX.findall(page_html)

  @memoized_method
  def get_imported_repo(self, import_path):
    """Looks for a go-import meta tag for the provided import_path.

    Returns an ImportedRepo instance with the information in the meta tag,
    or None if no go-import meta tag is found.
    """
    try:
      session = requests.session()
      # TODO: Support https with (optional) fallback to http, as Go does.
      # See https://github.com/pantsbuild/pants/issues/3503.
      session.mount("http://",
                    requests.adapters.HTTPAdapter(max_retries=self.get_options().retries))
      page_data = session.get('http://{import_path}?go-get=1'.format(import_path=import_path))
    except requests.ConnectionError:
      return None

    if not page_data:
      return None

    # Return the first match, rather than doing some kind of longest prefix search.
    # Hopefully no one returns multiple valid go-import meta tags.
    for (root, vcs, url) in self.find_meta_tags(page_data.text):
      if root and vcs and url:
        # Check to make sure returned root is an exact match to the provided import path. If it is
        # not then run a recursive check on the returned and return the values provided by that call.
        if root == import_path:
          return ImportedRepo(root, vcs, url)
        elif import_path.startswith(root):
          return self.get_imported_repo(root)

    return None
