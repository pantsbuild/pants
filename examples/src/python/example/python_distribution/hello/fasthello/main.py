# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

# hello_package is a python module within the fasthello python_distribution
from hello_package import hello


if __name__ == '__main__':
  print(hello.hello())
