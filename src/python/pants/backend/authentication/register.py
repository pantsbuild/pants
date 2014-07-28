# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.authentication.netrc_util import Netrc
from pants.base.build_file_aliases import BuildFileAliases


def build_file_aliases():
  return BuildFileAliases.create(
    objects={
      'netrc': Netrc,
    },
  )
