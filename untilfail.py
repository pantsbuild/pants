#!/usr/bin/env python3

import time
import subprocess
import sys

start_time = time.time()
previous_time = start_time
count = 0
while True:
    count += 1
    new_time = time.time()
    print(f"Attempt #{count} -- time elapsed since last test: {int(new_time - previous_time)}, total time elapsed: {int(new_time - start_time)}")
    previous_time = new_time
    try:
        subprocess.run(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
      print(e.stdout.decode())
      print(e.stderr.decode())
      print(f"Total time elapsed: {int(time.time() - start_time)}")
      raise
