# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.rules import console_rule
from pants.engine.selectors import Select


@console_rule('list', [Select(Console), Select(BuildFileAddresses)])
def fast_list(console, addresses):
  """A fast variant of `./pants list` with a reduced feature set."""
  for address in addresses.dependencies:
    console.print_stdout(address.spec)
