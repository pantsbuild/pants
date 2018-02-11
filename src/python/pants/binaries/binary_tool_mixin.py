# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import create_binary_tool_cls
from pants.util.memo import memoized_method


class BinaryToolMixin(object):
  """Mixin for classes that use binary executables.

  Must be mixed in to something that can register and use options, e.g., a Task or a Subsystem.

  :API: public
  """
  @classmethod
  def binary_tool_subsystem(cls, *args, **kwargs):
    """See create_binary_tool_cls() for method arguments."""
    return create_binary_tool_cls(*args, **kwargs)


  @memoized_method
  def select_binary(self, name):
    return self._binary_tools_by_name[name].select(self.context.options)
