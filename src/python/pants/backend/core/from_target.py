# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.build_graph.from_target import FromTarget


deprecated_module('0.0.66',
                  hint_message='pants.backend.core.from_target has moved to '
                               'pants.build_graph.from_target. Replace deps on '
                               'src/python/pants/backend/core with a dep on '
                               'src/python/pants/build_graph and change imports accordingly.')


FromTarget = FromTarget
