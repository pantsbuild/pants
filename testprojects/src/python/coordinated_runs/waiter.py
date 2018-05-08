import os
import sys
import time

waiting_for_file = sys.argv[1]
while not os.path.isfile(waiting_for_file):
  sys.stderr.write("Waiting for file {}\n".format(waiting_for_file))
  time.sleep(1)
