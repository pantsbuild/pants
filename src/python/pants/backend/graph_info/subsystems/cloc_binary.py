# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import Script


class ClocBinary(Script):
  # Note: Not in scope 'cloc' because that's the name of the singleton task that runs cloc.
  options_scope = 'cloc-binary'
  name = 'cloc'
  default_version = '1.66'

  replaces_scope = 'cloc'
  replaces_name = 'version'
