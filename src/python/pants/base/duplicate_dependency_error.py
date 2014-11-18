# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class DuplicateDependencyError(Exception):
  """Raised when a dependency is specified twice.

  While not a serious error, it is better to give the user immediate feedback so
  the dupe can be removed.
  """
