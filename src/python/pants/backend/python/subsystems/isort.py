# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.binaries.binary_tool import Script


class Isort(Script):
  options_scope = 'isort'
  default_version = '4.3.4'
  suffix = '.pex'

  replaces_scope = 'fmt.isort'
  replaces_name = 'version'
