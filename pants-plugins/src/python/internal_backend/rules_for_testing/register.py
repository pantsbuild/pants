# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.rules import console_rule


class ListAndDieForTesting(Goal):
  """A fast and deadly variant of `./pants list`."""

  name = 'list-and-die-for-testing'


@console_rule(ListAndDieForTesting, [Console, BuildFileAddresses])
def fast_list_and_die_for_testing(console, addresses):
  for address in addresses.dependencies:
    console.print_stdout(address.spec)
  yield ListAndDieForTesting(exit_code=42)


def rules():
  return [
      fast_list_and_die_for_testing,
    ]
