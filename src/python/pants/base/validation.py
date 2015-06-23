# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from six import string_types
from twitter.common.collections import OrderedSet
from twitter.common.dirutil.fileset import Fileset

from pants.backend.core.wrapped_globs import FilesetWithSpec


def assert_list(obj, expected_type=string_types, can_be_none=True, default=(), key_arg=None,
    allowable=(list, Fileset, FilesetWithSpec, OrderedSet, set, tuple), raise_type=ValueError):
  """
  This function is used to ensure that parameters set by users in BUILD files are of acceptable types.
  :param obj           : the object that may be a list. It will pass if it is of type in allowable.
  :param expected_type : this is the expected type of the returned list contents.
  :param can_be_none   : this defines whether or not the obj can be None. If True, return default.
  :param default       : this is the default to return if can_be_none is True and obj is None.
  :param key_arg       : this is the name of the key to which obj belongs to
  :param allowable     : the acceptable types for obj. We do not want to allow any iterable (eg string).
  :param raise_type    : the error to throw if the type is not correct.
  """
  def get_key_msg(key=None):
    if key is None:
      return ''
    else:
      return "In key '{}': ".format(key)

  key_msg = get_key_msg(key_arg)
  val = obj
  if val is None:
    if can_be_none:
      val = list(default)
    else:
      raise raise_type(
        '{}Expected an object of acceptable type {}, received None and can_be_none is False'
          .format(key_msg, allowable))

  if isinstance(val, allowable):
    lst = list(val)
    for e in lst:
      if not isinstance(e, expected_type):
        raise raise_type(
            '{}Expected a list containing values of type {}, instead got a value {} of {}'
            .format(key_msg, expected_type, e, e.__class__))
    return lst
  else:
    raise raise_type(
        '{}Expected an object of acceptable type {}, received {} instead'
        .format(key_msg, allowable, val))
