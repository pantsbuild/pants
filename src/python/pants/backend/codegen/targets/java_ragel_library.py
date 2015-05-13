# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget


class JavaRagelLibrary(JvmTarget):
  """Generates a stub Java library from a Ragel file."""

  def __init__(self, **kwargs):
    super(JavaRagelLibrary, self).__init__(**kwargs)

    self.add_labels('codegen')
