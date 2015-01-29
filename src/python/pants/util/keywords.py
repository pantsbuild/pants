# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import functools
import keyword
import os
import re

from pants.util.contextutil import temporary_file
from pants.util.fileutil import atomic_copy
from pants.util.strutil import ensure_binary


kwlist = keyword.kwlist + [
  'None',
  'Exception',
  'True',
  'False',
]


def replace_python_keywords_in_file(source):
  """Replaces the python keywords in the (presumably thrift) file

  Find all python keywords in the file named `source` and appends a
  trailing underscore.  For example, 'from' will be converted to
  'from_'.

  Also replaces some non-keywords that should not be assigned to
  e.g. None.

  """

  rewrites = []
  # Use binary strings here as data read from files is binary, and mixing
  # binary and text can cause problems
  renames = dict((ensure_binary(kw), b'%s_' % kw) for kw in kwlist)
  token_regex = re.compile(r'\b(%s)\b' % '|'.join(renames.keys()), re.MULTILINE)

  def token_replace(match):
    return renames[match.group(1)]

  def replace_tokens(contents):
    return token_regex.sub(token_replace, contents)

  rewrites.append(replace_tokens)
  with open(source) as contents:
    modified = functools.reduce(lambda txt, rewrite: rewrite(txt), rewrites, contents.read())
    contents.close()
    with temporary_file() as thrift:
      thrift.write(modified)
      thrift.close()
      atomic_copy(thrift.name, source)
  return source
