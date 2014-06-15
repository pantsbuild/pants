# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import sys

# A useful binary for testing which interpreter the pex machinery selects.

v = sys.version_info
print('%d.%d.%d' % v[0:3])
