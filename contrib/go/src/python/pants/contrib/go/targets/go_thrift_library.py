# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_conditional
from pants.build_graph.target import Target

from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_target import GoTarget


class GoThriftLibrary(Target):
  """A Go library generated from Thrift IDL files."""

  def __init__(self, import_path=None, **kwargs):
    deprecated_conditional(lambda: import_path is not None,
                           removal_version='1.6.0.dev0',
                           entity_description='import_path',
                           hint_message='Remove this unused {} parameter'.format(self.alias()))

    super(GoThriftLibrary, self).__init__(**kwargs)

  @classmethod
  def alias(cls):
    return "go_thrift_library"


class GoThriftGenLibrary(GoTarget):
  @property
  def import_path(self):
    """The import path as used in import statements in `.go` source files."""
    return GoLocalSource.local_import_path(self.target_base, self.address)
