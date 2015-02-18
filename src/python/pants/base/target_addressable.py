# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from six import string_types

from pants.base.addressable import Addressable
from pants.base.exceptions import TargetDefinitionException


class TargetAddressable(Addressable):
  @classmethod
  def get_target_type(cls):
    raise NotImplemented

  @property
  def addressable_name(self):
    return self.name

  def __init__(self, *args, **kwargs):
    self.target_type = self.get_target_type()

    if 'name' not in kwargs:
      raise Addressable.AddressableInitError(
        'name is a required parameter to all Targets specified within a BUILD file.'
        '  Target type was: {target_type}.'
        .format(target_type=self.target_type))

    if args:
      raise Addressable.AddressableInitError(
        'All arguments passed to Targets within BUILD files must use explicit keyword syntax.'
        '  Target type was: {target_type}.'
        '  Arguments passed were: {args}'
        .format(target_type=self.target_type, args=args))

    self.kwargs = kwargs
    self.name = kwargs['name']
    self.dependency_specs = self.kwargs.pop('dependencies', [])

    for dep_spec in self.dependency_specs:
      if not isinstance(dep_spec, string_types):
        msg = ('dependencies passed to Target constructors must be strings.  {dep_spec} is not'
               ' a string.  Target type was: {target_type}.'
               .format(target_type=self.target_type, dep_spec=dep_spec))
        raise TargetDefinitionException(target=self, msg=msg)

  def with_description(self, description):
    self.kwargs['description'] = description

  def __str__(self):
    format_str = 'TargetAddressable(target_type={target_type}, name={name}, **kwargs=...)'
    return format_str.format(target_type=self.target_type, name=self.name)

  def __repr__(self):
    format_str = 'TargetAddressable(target_type={target_type}, kwargs={kwargs})'
    return format_str.format(target_type=self.target_type, kwargs=self.kwargs)
