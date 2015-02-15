# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib


def hash_all(strs, digest=None):
  """Returns a hash of the concatenation of all the strings in strs.

  If a hashlib message digest is not supplied a new sha1 message digest is used.
  """
  digest = digest or hashlib.sha1()
  for s in strs:
    digest.update(s)
  return digest.hexdigest()


def hash_file(path, digest=None):
  """Hashes the contents of the file at the given path and returns the hash digest in hex form.

  If a hashlib message digest is not supplied a new sha1 message digest is used.
  """
  digest = digest or hashlib.sha1()
  with open(path, 'rb') as fd:
    s = fd.read(8192)
    while s:
      digest.update(s)
      s = fd.read(8192)
  return digest.hexdigest()
