# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from pants.util.memo import memoized


class Sources(object):
  @classmethod
  @memoized
  def of(cls, ext):
    type_name = b'Sources({!r})'.format(ext)

    class_dict = {'ext': ext,
                  # We need custom serialization for the dynamic class type.
                  '__reduce__': lambda self: (_create_sources, ext)}

    ext_type = type(type_name, (cls,), class_dict)

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, ext_type)

    return ext_type

  @classmethod
  def ext(cls):
    raise NotImplementedError()

  def __repr__(self):
    return 'Sources(ext={!r})'.format(self.ext)
