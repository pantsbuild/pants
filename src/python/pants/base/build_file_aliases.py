# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro


deprecated_module('0.0.53', hint_message='Use pants.build_graph.build_file_aliases instead.')

TargetMacro = TargetMacro
BuildFileAliases = BuildFileAliases
