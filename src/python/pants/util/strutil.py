# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
import shlex

import six


def ensure_binary(text_or_binary):
  if isinstance(text_or_binary, six.binary_type):
    return text_or_binary
  elif isinstance(text_or_binary, six.text_type):
    return text_or_binary.encode('utf8')
  else:
    raise TypeError('Argument is neither text nor binary type.({})'.format(type(text_or_binary)))


def ensure_text(text_or_binary):
  if isinstance(text_or_binary, six.binary_type):
    return text_or_binary.decode('utf-8')
  elif isinstance(text_or_binary, six.text_type):
    return text_or_binary
  else:
    raise TypeError('Argument is neither text nor binary type ({})'.format(type(text_or_binary)))


def is_text_or_binary(obj):
  return isinstance(obj, (six.text_type, six.binary_type))


def safe_shlex_split(text_or_binary):
  """Split a string using shell-like syntax.

  Safe even on python versions whose shlex.split() method doesn't accept unicode.
  """
  return shlex.split(ensure_binary(text_or_binary))


def camelcase(string):
  """Convert snake casing (containing - or _ characters) to camel casing."""
  return ''.join(word.capitalize() for word in re.split('[-_]', string))


def pluralize(count, item_type):
  """Pluralizes the item_type if the count does not equal one.

  For example `pluralize(1, 'apple')` returns '1 apple',
  while `pluralize(0, 'apple') returns '0 apples'.

  :return The count and inflected item_type together as a string
  :rtype string
  """
  def pluralize_string(x):
    if x.endswith('s'):
      return x + 'es'
    else:
      return x + 's'

  text = '{} {}'.format(count, item_type if count == 1 else pluralize_string(item_type))
  return text


def strip_prefix(string, prefix):
  """Returns a copy of the string from which the multi-character prefix has been stripped.

  Use strip_prefix() instead of lstrip() to remove a substring (instead of individual characters)
  from the beginning of a string, if the substring is present.  lstrip() does not match substrings
  but rather treats a substring argument as a set of characters.

  :param str string: The string from which to strip the specified prefix.
  :param str prefix: The substring to strip from the left of string, if present.
  :return: The string with prefix stripped from the left, if present.
  :rtype: string
  """
  if string.startswith(prefix):
    return string[len(prefix):]
  else:
    return string
