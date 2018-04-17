# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.binaries.binary_tool import NativeTool


logger = logging.getLogger(__name__)


class YarnpkgDistribution(NativeTool):
  """Represents a self-bootstrapping Yarnpkg distribution."""

  options_scope = 'yarnpkg-distribution'
  name = 'yarnpkg'
  default_version = 'v0.19.1'
  archive_type = 'tgz'
