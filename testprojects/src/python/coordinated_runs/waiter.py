# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import os
import sys
import time

waiting_for_file = sys.argv[1]
pid_file = sys.argv[2]
attempts = 60
with open(pid_file, "w") as pf:
    pf.write(str(os.getpid()))
while not os.path.isfile(waiting_for_file):
    if attempts <= 0:
        raise Exception("File was never written.")
    attempts -= 1
    sys.stderr.write("Waiting for file {}\n".format(waiting_for_file))
    time.sleep(1)
