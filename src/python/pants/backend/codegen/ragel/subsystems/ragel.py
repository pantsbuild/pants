# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import NativeTool


class Ragel(NativeTool):
  options_scope = 'ragel'
  default_version = '6.9'

  replaces_scope = 'gen.ragel'
  replaces_name = 'version'
