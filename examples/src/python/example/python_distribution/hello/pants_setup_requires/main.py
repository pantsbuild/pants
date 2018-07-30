# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import pkg_resources


hello_module_version = pkg_resources.get_distribution('hello_again').version

if __name__ == '__main__':
  print(hello_module_version)
