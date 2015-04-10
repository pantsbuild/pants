# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.build_file_layout.source_root import SourceRoot
from pants.backend.build_file_layout.source_root_layout import SingletonSourceRootLookup
from pants.base.build_file_aliases import BuildFileAliases


def build_file_aliases():
  return BuildFileAliases.create(
    context_aware_object_factories={
      'source_root': SourceRoot.factory,
    }
  )

def register_layouts():
  return [SingletonSourceRootLookup()]
