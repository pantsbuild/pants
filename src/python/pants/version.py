# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pkgutil

from packaging.version import Version


VERSION = pkgutil.get_data(__name__, 'VERSION').strip()

PANTS_SEMVER = Version(VERSION)
