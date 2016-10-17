# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.build_graph.codegen_library_mixin import CodegenLibraryMixin


class JavaRagelLibrary(CodegenLibraryMixin, JvmTarget):
  """A Java library generated from a Ragel file."""
