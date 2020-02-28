import os
import sys
import time

waiting_for_file = sys.argv[1]
attempts = 60
while not os.path.isfile(waiting_for_file):
    if attempts <= 0:
        raise Exception("File was never written.")
    attempts -= 1
    sys.stderr.write("Waiting for file {}\n".format(waiting_for_file))
    time.sleep(1)
