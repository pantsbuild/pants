# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from super_greet import super_greet


def superhello(greetee):
  """Given the name, return a super greeting for a person of that name."""
  return '{}, {}'.format(super_greet(), greetee)
