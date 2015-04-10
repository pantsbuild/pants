# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.build_file_layout.source_root import SourceRoot
from pants.base.layout import SourceRootLookup


class SingletonSourceRootLookup(SourceRootLookup):
  def all_roots(self):
    # returns dict {path -> types}
    return SourceRoot.all_roots()

  def roots_by_type(self, type):
    # returns list of roots
    return SourceRoot.roots(type)

  def find_root(self, sub_path):
    # returns (path, types)
    path = SourceRoot.find_by_path(sub_path)
    if path:
      return (path, SourceRoot.types(path))
    else:
      return None
