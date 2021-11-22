# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import os
import sys
import time
from multiprocessing import Process

waiting_for_file = sys.argv[1]
pid_file = sys.argv[2]
child_pid_file = sys.argv[3]
attempts = 60


def run_child():
    while True:
        print("Child running...")
        time.sleep(1)


child = Process(target=run_child, daemon=True)
child.start()

with open(child_pid_file, "w") as pf:
    pf.write(str(child.pid))

with open(pid_file, "w") as pf:
    pf.write(str(os.getpid()))

try:
    while not os.path.isfile(waiting_for_file):
        if attempts <= 0:
            raise Exception("File was never written.")
        attempts -= 1
        sys.stderr.write("Waiting for file {}\n".format(waiting_for_file))
        time.sleep(1)
finally:
    child.terminate()
