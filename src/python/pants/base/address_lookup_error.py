# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class AddressLookupError(Exception):
  """Raised by various modules when an address can't be resolved.  Use this common base class so
   other modules can trap the error at each node along the path and construct a useful diagnostic.
  """
