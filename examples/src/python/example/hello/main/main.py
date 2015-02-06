# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from example.hello.greet.greet import greet


if __name__ == '__main__':
  greetees = sys.argv[1:] or ['world']
  for greetee in greetees:
    print(greet(greetee))
