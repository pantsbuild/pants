# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.graph_info.tasks.dependees import ReverseDepmap
from pants.base.deprecated import deprecated_module


deprecated_module('0.0.66',
                  hint_message='pants.backend.core.tasks.dependees has moved to '
                               'pants.backend.graph_info.tasks. Replace deps on '
                               'src/python/pants/backend/core/tasks:* with a dep on '
                               'src/python/pants/backend/graph_info/tasks and change '
                               'imports accordingly.')


ReverseDepmap = ReverseDepmap
