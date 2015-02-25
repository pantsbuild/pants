# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.address import BuildFileAddress
from pants.util.meta import AbstractClass


class AddressableCallProxy(object):
  """A registration proxy for objects to be captured and addressed from BUILD files."""

  def __init__(self, addressable_type, build_file, registration_callback):
    self._addressable_type = addressable_type
    self._build_file = build_file
    self._registration_callback = registration_callback

  def __call__(self, *args, **kwargs):
    addressable = self._addressable_type(*args, **kwargs)
    addressable_name = addressable.addressable_name
    if addressable_name:
      address = BuildFileAddress(self._build_file, addressable_name)
      self._registration_callback(address, addressable)
    return addressable

  def __repr__(self):
    return ('AddressableCallProxy(addressable_type={target_type}, build_file={build_file})'
            .format(target_type=self._addressable_type,
                    build_file=self._build_file))


class Addressable(AbstractClass):
  """An ABC for classes which would like instances to be named and exported from BUILD files."""

  class AddressableInitError(Exception): pass

  @property
  def addressable_name(self):
    """This property is inspected by AddressableCallProxy to automatically name Addressables.

    Generally, a subclass will inspect its captured arguments and return, for example, the
      captured `name` parameter.  A value of `None` (the default) causes AddressableCallProxy
      to skip capturing and naming this instance.
    """
    return None
