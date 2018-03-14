# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.deprecated import deprecated_conditional
from pants.binaries.binary_tool import NativeTool
from pants.util.memo import memoized_method


logger = logging.getLogger(__name__)


class YarnpkgDistribution(NativeTool):
  """Represents a self-bootstrapping Yarnpkg distribution."""

  options_scope = 'yarnpkg-distribution'
  name = 'yarnpkg'
  default_version = 'v0.19.1'
  archive_type = 'tgz'

  replaces_scope = 'node-distribution'
  replaces_name = 'yarnpkg_version'

  @memoized_method
  def version(self, context=None):
    # The versions reported by node and embedded in distribution package names are 'vX.Y.Z'.
    # TODO: After the deprecation cycle is over we'll expect the values of the version option
    # to already include the 'v' prefix, so there will be no need to normalize, and we can
    # delete this entire method override.
    version = super(YarnpkgDistribution, self).version(context)
    deprecated_conditional(
      lambda: not version.startswith('v'), entity_description='', removal_version='1.7.0.dev0',
      hint_message='value of --version in scope {} must be of the form '
                   'vX.Y.Z'.format(self.options_scope))
    return version if version.startswith('v') else 'v' + version
