# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time


def test_within_timeout():
  time.sleep(0.1)


def test_exceeds_timeout():
  time.sleep(120)
