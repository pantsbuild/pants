# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys


if __name__ == "__main__":
  print("Shouldn't have reached this point. This should have crashed when resolving badreq")
  sys.exit(1)
