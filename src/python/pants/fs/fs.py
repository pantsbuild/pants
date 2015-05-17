# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os


# This is the max filename length for HFS+, extX and NTFS - the most likely filesystems pants will
# be run under.
# TODO(John Sirois): consider a better isolation layer
_MAX_FILENAME_LENGTH = 255


def safe_filename(name, extension=None, digest=None, max_length=_MAX_FILENAME_LENGTH):
  """Creates filename from name and extension ensuring that the final length is within the
  max_length constraint.

  By default the length is capped to work on most filesystems and the fallback to achieve
  shortening is a sha1 hash of the proposed name.

  Raises ValueError if the proposed name is not a simple filename but a file path.
  Also raises ValueError when the name is simple but cannot be satisfactorily shortened with the
  given digest.

  name:       the proposed filename without extension
  extension:  an optional extension to append to the filename
  digest:     the digest to fall back on for too-long name, extension concatenations - should
              support the hashlib digest api of update(string) and hexdigest
  max_length: the maximum desired file name length
  """
  if os.path.basename(name) != name:
    raise ValueError('Name must be a filename, handed a path: {}'.format(name))

  ext = extension or ''
  filename = name + ext
  if len(filename) <= max_length:
    return filename
  else:
    digest = digest or hashlib.sha1()
    digest.update(name)
    safe_name = digest.hexdigest() + ext
    if len(safe_name) > max_length:
      raise ValueError('Digest {} failed to produce a filename <= {} '
                       'characters for {} - got {}'.format(digest, max_length, filename, safe_name))
    return safe_name


def expand_path(path):
  """Returns ``path`` as an absolute path with ~user and env var expansion applied."""
  return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
