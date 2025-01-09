# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import os
import sys
import time
from multiprocessing import Process


def run_child():
    while True:
        print("Child running...")
        time.sleep(1)


def main():
    waiting_for_file = sys.argv[1]
    pid_file = sys.argv[2]
    child_pid_file = sys.argv[3]
    cleanup_wait_time = int(sys.argv[4])
    attempts = 60

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
            sys.stderr.write(f"Waiting for file {waiting_for_file}\n")
            sys.stderr.flush()
            time.sleep(1)

    except KeyboardInterrupt:
        sys.stderr.write("keyboard int received\n")
        sys.stderr.flush()

    finally:
        sys.stderr.write("waiter cleaning up\n")
        sys.stderr.flush()

        child.terminate()
        if cleanup_wait_time > 0:
            time.sleep(cleanup_wait_time)

        sys.stderr.write("waiter cleanup complete\n")
        sys.stderr.flush()


if __name__ == "__main__":
    main()
