# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import six
import shlex


def ensure_binary(text_or_binary):
  if isinstance(text_or_binary, six.binary_type):
    return text_or_binary
  elif isinstance(text_or_binary, six.text_type):
    return text_or_binary.encode('utf8')
  else:
    raise TypeError('Argument is neither text nor binary type.')


def safe_shlex_split(text_or_binary):
  """Split a string using shell-like syntax.

  Safe even on python versions whose shlex.split() method doesn't accept unicode.
  """
  return shlex.split(ensure_binary(text_or_binary))
