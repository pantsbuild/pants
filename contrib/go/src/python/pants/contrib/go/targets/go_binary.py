# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.go.targets.go_local_source import GoLocalSource


class GoBinary(GoLocalSource):
  """A local Go main package."""

  @classmethod
  def alias(cls):
    return 'go_binary'

  def __init__(self, build_flags=None, **kwargs):
    """
    :param string build_flags: Build flags to pass to Go compiler.
    """
    super(GoBinary, self).__init__(**kwargs)
    self.build_flags = build_flags
