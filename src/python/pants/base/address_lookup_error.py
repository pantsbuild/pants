# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.build_graph.address_lookup_error import AddressLookupError


deprecated_module('0.0.55', hint_message='Use pants.build_graph.address_lookup_error instead.')

AddressLookupError = AddressLookupError
