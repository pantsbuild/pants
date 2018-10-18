# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.exceptions import GracefulTerminationException
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.rules import console_rule
from pants.engine.selectors import Select


@console_rule('list', [Select(Console), Select(BuildFileAddresses)])
def fast_list(console, addresses):
  """A fast variant of `./pants list` with a reduced feature set."""
  for address in addresses.dependencies:
    console.print_stdout(address.spec)


# This should really be registered somehow as an in-repo plugin when testing, rather than living
# inside pants.rules.core and always being registered as an available console_rule.
# But we can't currently do that, so... Here it is :)
# See https://github.com/pantsbuild/pants/issues/6652
@console_rule('list-and-die-for-testing', [Select(Console), Select(BuildFileAddresses)])
def fast_list_and_die_for_testing(console, addresses):
  """A fast variant of `./pants list` with a reduced feature set."""
  for address in addresses.dependencies:
    console.print_stdout(address.spec)
  raise GracefulTerminationException(exit_code=42)
