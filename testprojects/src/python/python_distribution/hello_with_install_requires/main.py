# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import pycountry
from hello_package import hello


if __name__ == '__main__':
  hello.hello()
  print(pycountry.countries.get(alpha_2='US').name)
