# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.rules import console_rule
from pants.engine.selectors import Get, Select
from pants.option.scope import Scope, ScopedOptions
from pants.rules.core.exceptions import GracefulTerminationException


@console_rule('list-and-die-for-testing', [Select(Console), Select(BuildFileAddresses)])
def fast_list_and_die_for_testing(console, addresses):
  """A fast and deadly variant of `./pants list`."""
  options = yield Get(ScopedOptions, Scope(str('list')))
  console.print_stderr('>>> Got an interesting option: {}'.format(options.options.documented))
  for address in addresses.dependencies:
    console.print_stdout(address.spec)
  raise GracefulTerminationException(exit_code=42)


def rules():
  return (fast_list_and_die_for_testing,)
