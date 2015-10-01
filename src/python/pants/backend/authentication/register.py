# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.authentication.netrc_util import Netrc
from pants.build_graph.build_file_aliases import BuildFileAliases


def build_file_aliases():
  return BuildFileAliases(
    objects={
      'netrc': Netrc,
    },
  )
