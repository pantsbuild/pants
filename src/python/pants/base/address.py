# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.build_graph.address import Address, Addresses, BuildFileAddress, parse_spec


deprecated_module('0.0.55', hint_message='Use pants.build_graph.address instead.')

Address = Address
Addresses = Addresses
BuildFileAddress = BuildFileAddress
parse_spec = parse_spec
