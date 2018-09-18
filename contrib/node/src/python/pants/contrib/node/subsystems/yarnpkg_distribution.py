# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.binaries.binary_tool import NativeTool


logger = logging.getLogger(__name__)


class YarnpkgDistribution(NativeTool):
  """Represents a self-bootstrapping Yarnpkg distribution."""

  options_scope = 'yarnpkg-distribution'
  name = 'yarnpkg'
  default_version = 'v1.6.0'
  archive_type = 'tgz'
