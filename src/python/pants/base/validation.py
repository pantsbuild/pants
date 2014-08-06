# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet
from twitter.common.dirutil.fileset import Fileset
from twitter.common.lang import Compatibility

def assert_list(obj, expected_type=Compatibility.string, can_be_none=True, default=(),
    allowable=(list, Fileset, OrderedSet, set, tuple), raise_type=ValueError):
  """
  This function is used to ensure that parameters set by users in BUILD files are of acceptable types.
  :param obj           : the object that may be a list. It will pass if it is of type in allowable.
  :param expected_type : this is the expected type of the returned list contents.
  :param can_be_none   : this defines whether or not the obj can be None. If True, return default.
  :param default       : this is the default to return if can_be_none is True and obj is None.
  :param allowable     : the acceptable types for obj. We do not want to allow any iterable (eg string).
  :param raise_type    : the error to throw if the type is not correct.
  """
  val = obj
  if val is None:
    if can_be_none:
      val = list(default)
    else:
      raise raise_type('Expected an object of acceptable type %s, received None and can_be_none is False' % allowable)

  if [typ for typ in allowable if isinstance(val, typ)]:
    lst = list(val)
    for e in lst:
      if not isinstance(e, expected_type):
        raise raise_type('Expected a list containing values of type %s, instead got a value %s of %s' %
          (expected_type, e, e.__class__))
    return lst
  else:
    raise raise_type('Expected an object of acceptable type %s, received %s instead' % (allowable, val))
