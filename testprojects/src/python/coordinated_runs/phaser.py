# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
import time

arrive_file, await_file = sys.argv[1:3]

# Signal we've arrived.
with open(arrive_file, "w") as fp:
    fp.close()

# Await a graceful join.
while not os.path.isfile(await_file):
    time.sleep(0.1)
