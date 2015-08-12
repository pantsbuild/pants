# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.base.build_file import FilesystemBuildFile


# A regex to recognize substrings that are probably URLs or file paths. Broken down for readability.
_PREFIX = r'(https?://)?/?'  # http://, https:// or / or nothing.
_OPTIONAL_PORT = r'(:\d+)?'
_REL_PATH_COMPONENT = r'(\w|[-.])+'  # One or more alphanumeric, underscore, dash or dot.
_ABS_PATH_COMPONENT = r'/' + _REL_PATH_COMPONENT
_ABS_PATH_COMPONENTS = r'({})+'.format(_ABS_PATH_COMPONENT)
_OPTIONAL_TARGET_SUFFIX = r'(:{})?'.format(_REL_PATH_COMPONENT)  # For /foo/bar:target.

# Note that we require at least two path components.
# We require the last character to be alphanumeric or underscore, because some tools print an
# ellipsis after file names (I'm looking at you, zinc). None of our files end in a dot in practice,
# so this is fine.
_PATH = _PREFIX + _REL_PATH_COMPONENT + _OPTIONAL_PORT + _ABS_PATH_COMPONENTS + \
        _OPTIONAL_TARGET_SUFFIX + '\w'
_PATH_RE = re.compile(_PATH)

_NO_URL = "no url"  # Sentinel value for non-existent files in linkify's memo


def linkify(buildroot, s, memoized_urls):
  """Augment text by heuristically finding URL and file references and turning them into links.

  :param string buildroot: The base directory of the project.
  :param string s: The text to insert links into.
  :param dict memoized_urls: A cache of text to links so repeated substitutions don't require
                             additional file stats calls.
  """
  def memoized_to_url(m):
    # to_url uses None to signal not to replace the text,
    # so we use a different sentinel value.
    value = memoized_urls.get(m.group(0), _NO_URL)
    if value is _NO_URL:
      value = to_url(m)
      memoized_urls[m.group(0)] = value
    return value

  def to_url(m):
    if m.group(1):
      return m.group(0)  # It's an http(s) url.
    path = m.group(0)

    if path.startswith('/'):
      path = os.path.relpath(path, buildroot)
    else:
      # See if it's a reference to a target in a BUILD file.
      parts = path.split(':')
      if len(parts) == 2:
        putative_dir = parts[0]
      else:
        putative_dir = path
      if os.path.isdir(os.path.join(buildroot, putative_dir)):
        build_file = FilesystemBuildFile.from_cache(buildroot, putative_dir, must_exist=False)
        path = build_file.relpath
    if os.path.exists(os.path.join(buildroot, path)):
      # The reporting server serves file content at /browse/<path_from_buildroot>.
      return '/browse/{}'.format(path)
    else:
      return None

  def maybe_add_link(url, text):
    return '<a target="_blank" href="{}">{}</a>'.format(url, text) if url else text

  return _PATH_RE.sub(lambda m: maybe_add_link(memoized_to_url(m), m.group(0)), s)
