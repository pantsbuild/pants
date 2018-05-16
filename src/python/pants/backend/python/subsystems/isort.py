# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import Script


class Isort(Script):
  options_scope = 'isort'
  default_version = '4.2.5'
  suffix = '.pex'

  replaces_scope = 'fmt.isort'
  replaces_name = 'version'
